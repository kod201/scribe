"""Stage 3: extract (PRD 5.1, 7).

Whole-page mode: every field is asked against the full page image. The
document_type field doubles as the page-type classifier and runs first; the
remaining fields are those applicable to the classified type.

Idempotent by the (page_id, field_name, prompt_version) unique key: pages that
already have a row for a field are skipped, so an interrupted run resumes.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import Connection
from typing import Any, Callable

from scribe.config import Config
from scribe.engines.base import ExtractionEngine, RawCompletion
from scribe.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    envelope_schema,
    field_user_prompt,
    repair_user_prompt,
)
from scribe.schema import FieldDef, Schema
from scribe.engines.base import LayoutEngine
from scribe.stages.jsonrepair import parse_model_json
from scribe.stages.validate import evaluate_cross_field_rules, validate_field

PAGE_TYPE_FIELD = "document_type"

CROP_CONTEXT = (
    "The image is a cropped region of the page believed to contain this "
    "field. If the field is genuinely not visible in this crop, return "
    "value=null, legible=true, and say 'not in crop' in note."
)


def effective_prompt_version(
    layout: LayoutEngine | None, crop_field_types: list[str] | None = None,
    verify_pass: bool = False, verify_model: str | None = None,
) -> str:
    """Crop, routed-crop and whole-page outputs never mix under one key."""
    if layout is None or layout.name == "none":
        return PROMPT_VERSION
    v = PROMPT_VERSION + "+crop:" + layout.name
    if crop_field_types:
        v += ":r=" + ",".join(sorted(crop_field_types))
    if verify_pass:
        v += "+verify"
        if verify_model:
            v += ":" + verify_model.rsplit("/", 1)[-1]
    return v


@dataclass
class FieldExtraction:
    """Everything that goes into one extractions row."""

    field_name: str
    value: Any
    raw_transcription: str | None
    legible: bool | None
    note: str | None
    model_confidence: float | None
    composite_confidence: float | None
    validation_status: str
    validation_errors: list[str]
    flagged: bool
    flag_reason: str | None
    latency_ms: int
    region_id: str | None = None
    crop_path: str | None = None


def extract_field(
    engine: ExtractionEngine,
    schema: Schema,
    fd: FieldDef,
    image_path: Path,
    default_threshold: float,
    is_crop: bool = False,
) -> FieldExtraction:
    """One field against one image (page or crop): prompt, parse, one repair
    retry, validate (PRD 7.2)."""
    user = field_user_prompt(fd, schema)
    if is_crop:
        user = CROP_CONTEXT + "\n\n" + user
    js = envelope_schema(fd)

    completion = engine.complete(
        system=SYSTEM_PROMPT, user=user, images=[image_path], json_schema=js,
    )
    latency = completion.latency_ms
    envelope = parse_model_json(completion.text)

    if envelope is None:
        # One retry with a repair prompt (PRD 7.2), unconstrained wording but
        # the same grammar constraint if the backend supports it.
        retry = engine.complete(
            system=SYSTEM_PROMPT,
            user=user + "\n\n" + repair_user_prompt(fd),
            images=[image_path],
            json_schema=js,
        )
        latency += retry.latency_ms
        envelope = parse_model_json(retry.text)

    if envelope is None:
        return FieldExtraction(
            field_name=fd.name, value=None, raw_transcription=None,
            legible=None, note=None, model_confidence=None,
            composite_confidence=0.0,
            validation_status="unparsed",
            validation_errors=["model output was not parseable JSON after retry"],
            flagged=True, flag_reason="unparseable model output",
            latency_ms=round(latency),
        )

    raw_value = envelope.get("value")
    legible = bool(envelope.get("legible", False))
    conf = envelope.get("confidence")
    model_conf = float(conf) if isinstance(conf, (int, float)) else 0.0
    raw_transcription = envelope.get("raw_transcription")
    if raw_transcription is not None:
        raw_transcription = str(raw_transcription)
    note = envelope.get("note")
    if note is not None:
        note = str(note)

    outcome = validate_field(
        fd, raw_value, legible, model_conf, raw_transcription, default_threshold,
    )
    return FieldExtraction(
        field_name=fd.name,
        value=outcome.value,
        raw_transcription=raw_transcription,
        legible=legible,
        note=note,
        model_confidence=model_conf,
        composite_confidence=outcome.composite,
        validation_status=outcome.validation_status,
        validation_errors=outcome.validation_errors,
        flagged=outcome.flagged,
        flag_reason=outcome.flag_reason,
        latency_ms=round(latency),
    )


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------


def _store(
    conn: Connection, page_id: str, engine: ExtractionEngine,
    fx: FieldExtraction, prompt_version: str
) -> None:
    conn.execute(
        "INSERT INTO extractions"
        " (extraction_id, page_id, field_name, region_id, crop_path, value,"
        "  raw_transcription, legible, note, model_confidence,"
        "  composite_confidence, validation_status, validation_errors, flagged,"
        "  flag_reason, model_name, model_version, prompt_version, latency_ms,"
        "  created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            uuid.uuid4().hex[:16], page_id, fx.field_name,
            fx.region_id, fx.crop_path,
            json.dumps(fx.value, ensure_ascii=False),
            fx.raw_transcription,
            None if fx.legible is None else int(fx.legible),
            fx.note, fx.model_confidence, fx.composite_confidence,
            fx.validation_status,
            json.dumps(fx.validation_errors, ensure_ascii=False),
            int(fx.flagged), fx.flag_reason,
            engine.name + ":" + getattr(engine, "model", "?"),
            engine.version, prompt_version,
            fx.latency_ms, datetime.now(timezone.utc).isoformat(),
        ),
    )


def _existing_fields(
    conn: Connection, page_id: str, prompt_version: str
) -> set[str]:
    return {
        r["field_name"]
        for r in conn.execute(
            "SELECT field_name FROM extractions"
            " WHERE page_id = ? AND prompt_version = ?",
            (page_id, prompt_version),
        )
    }


# ---------------------------------------------------------------------------
# page + document orchestration
# ---------------------------------------------------------------------------


def _locate_and_crop(
    conn: Connection,
    cfg: Config,
    layout: LayoutEngine,
    schema: Schema,
    page_row: Any,
    field_names: list[str],
) -> dict[str, tuple[str, str]]:
    """Localize fields on a page, persist regions + crops. Returns
    {field_name: (region_id, crop_path)} for the fields that were located."""
    page_id = page_row["page_id"]
    image_path = Path(page_row["image_path"])
    wanted = []
    for name in field_names:
        fd = schema.field(name)
        desc = fd.locate_hint or fd.extract_hint or f"the {name} field"
        kind = "the entire table including headers and every row" \
            if fd.type == "table" else "the value (handwritten or ticked)"
        wanted.append((name, f"{kind}: {desc}"))

    boxes = layout.locate_fields(image_path, wanted)
    out: dict[str, tuple[str, str]] = {}
    crops_dir = Path(cfg.paths.work) / page_row["doc_id"] / "crops"
    from scribe.engines.grounding import crop_region

    for name, bbox in boxes.items():
        region_id = uuid.uuid4().hex[:16]
        crop_path = crops_dir / f"p{page_row['page_no']:04d}_{name}.png"
        crop_region(image_path, bbox, crop_path, cfg.crop_margin_px)
        conn.execute(
            "INSERT INTO regions (region_id, page_id, bbox, region_type,"
            " layout_engine, engine_version) VALUES (?,?,?,?,?,?)",
            (region_id, page_id, json.dumps(list(bbox)), "field",
             layout.name, layout.version),
        )
        out[name] = (region_id, str(crop_path))
    return out


def extract_page(
    conn: Connection,
    cfg: Config,
    engine: ExtractionEngine,
    schema: Schema,
    page_row: Any,
    progress: Callable[[str], None] = lambda _msg: None,
    layout: LayoutEngine | None = None,
    verify_engine: ExtractionEngine | None = None,
) -> dict[str, Any]:
    """All applicable fields for one page. Returns the record dict of coerced
    values (for cross-field rules)."""
    page_id = page_row["page_id"]
    image_path = Path(page_row["image_path"])
    pv = effective_prompt_version(
        layout, cfg.crop_field_types, cfg.verify_pass,
        cfg.verify_engine.model if cfg.verify_engine else None,
    )
    done = _existing_fields(conn, page_id, pv)
    record: dict[str, Any] = {}

    def _reuse(field_name: str) -> Any:
        row = conn.execute(
            "SELECT value FROM extractions WHERE page_id=? AND field_name=?"
            " AND prompt_version=?",
            (page_id, field_name, pv),
        ).fetchone()
        return json.loads(row["value"]) if row and row["value"] else None

    # -- classify (or reuse the stored classification) ---------------------
    # Classification always sees the whole page: it needs global layout, and
    # localizing before knowing the page type would be circular.
    page_type = page_row["page_type"]
    type_field = schema.field(PAGE_TYPE_FIELD) if _has_type_field(schema) else None
    if type_field is not None:
        if PAGE_TYPE_FIELD in done:
            record[PAGE_TYPE_FIELD] = _reuse(PAGE_TYPE_FIELD)
        else:
            progress(f"{PAGE_TYPE_FIELD}")
            fx = extract_field(engine, schema, type_field, image_path,
                               cfg.review_threshold_default)
            _store(conn, page_id, engine, fx, pv)
            record[PAGE_TYPE_FIELD] = fx.value
        if record.get(PAGE_TYPE_FIELD) and record[PAGE_TYPE_FIELD] != page_type:
            page_type = record[PAGE_TYPE_FIELD]
            conn.execute("UPDATE pages SET page_type=? WHERE page_id=?",
                         (page_type, page_id))
    if page_type is None and schema.default_page_type:
        # Classifier nulled (or refused) and nothing is stored: route by the
        # schema's declared fallback instead of collapsing to every field.
        # The flagged classifier row stays in the review queue either way.
        page_type = schema.default_page_type
        conn.execute("UPDATE pages SET page_type=? WHERE page_id=?",
                     (page_type, page_id))

    # -- localize the remaining fields (crop mode) ---------------------------
    routed = set(cfg.crop_field_types or [])
    todo = [fd.name for fd in schema.fields_for(page_type)
            if fd.name != PAGE_TYPE_FIELD and fd.name not in done]
    # With a verify pass every field needs a crop (it is one of the two
    # sources); without one, only the routed types do.
    remaining = todo if cfg.verify_pass else [
        n for n in todo if not routed or schema.field(n).type in routed
    ]
    crops: dict[str, tuple[str, str]] = {}
    if layout is not None and layout.name != "none" and remaining:
        progress("locate")
        crops = _locate_and_crop(conn, cfg, layout, schema, page_row, remaining)

    # -- remaining fields ---------------------------------------------------
    for fd in schema.fields_for(page_type):
        if fd.name == PAGE_TYPE_FIELD:
            continue
        if fd.name in done:
            record[fd.name] = _reuse(fd.name)
            continue
        progress(fd.name)
        region_id, crop_path = crops.get(fd.name, (None, None))
        crop_primary = crop_path is not None and (
            not routed or fd.type in routed
        )
        fx = extract_field(
            engine, schema, fd,
            Path(crop_path) if crop_primary else image_path,
            cfg.review_threshold_default,
            is_crop=crop_primary,
        )
        fx.region_id, fx.crop_path = region_id, crop_path

        # Verify pass (PRD 7.3): re-read auto-accepted fields from the other
        # source; disagreement is the flag confidence cannot give us.
        if cfg.verify_pass and not fx.flagged and fx.value is not None:
            progress(f"{fd.name}:verify")
            # A distinct verifier model decorrelates shared biases; with one
            # configured, cross-source AND cross-model at once.
            veng = verify_engine or engine
            if crop_primary:
                vfx = extract_field(veng, schema, fd, image_path,
                                    cfg.review_threshold_default)
            elif crop_path:
                vfx = extract_field(veng, schema, fd, Path(crop_path),
                                    cfg.review_threshold_default, is_crop=True)
            elif verify_engine is not None:
                # No crop available, but a second model still gives an
                # independent read of the same page.
                vfx = extract_field(veng, schema, fd, image_path,
                                    cfg.review_threshold_default)
            else:
                vfx = None
            if vfx is not None:
                fx.latency_ms += vfx.latency_ms
                from scribe.stages.evaluate import values_match

                if not values_match(fx.value, vfx.value):
                    fx.flagged = True
                    fx.flag_reason = (
                        "verify pass disagreement: second read from the "
                        f"{'whole page' if crop_primary else 'crop'} gave "
                        + json.dumps(vfx.value, ensure_ascii=False)[:120]
                    )
                    fx.composite_confidence = (fx.composite_confidence or 0) * 0.5
                    if fx.note:
                        fx.note += f" | verify read: {vfx.raw_transcription!r}"
                    else:
                        fx.note = f"verify read: {vfx.raw_transcription!r}"

        _store(conn, page_id, engine, fx, pv)
        record[fd.name] = fx.value

    # -- cross-field rules ----------------------------------------------------
    failed = evaluate_cross_field_rules(schema.cross_field_rules, record)
    for expr in failed:
        rule = next(r for r in schema.cross_field_rules if r.rule == expr)
        names = _names_in(expr) & set(record)
        conn.execute(
            f"UPDATE extractions SET flagged=1,"
            f" flag_reason=COALESCE(flag_reason || '; ', '') || ?"
            f" WHERE page_id=? AND prompt_version=?"
            f" AND field_name IN ({','.join('?' * len(names))})",
            (f"cross-field rule failed: {rule.message or expr}",
             page_id, pv, *sorted(names)),
        )
    return record


def _has_type_field(schema: Schema) -> bool:
    return any(f.name == PAGE_TYPE_FIELD for f in schema.fields)


def _names_in(expr: str) -> set[str]:
    import ast

    return {
        n.id for n in ast.walk(ast.parse(expr, mode="eval"))
        if isinstance(n, ast.Name)
    }


def pages_to_extract(
    conn: Connection, doc_id: str | None = None
) -> list[Any]:
    """Pages of ingested documents, ordered. --doc narrows to one document."""
    q = (
        "SELECT p.*, d.schema_id AS doc_schema_id FROM pages p"
        " JOIN documents d USING (doc_id)"
        " WHERE d.status != 'failed'"
    )
    args: tuple[Any, ...] = ()
    if doc_id:
        q += " AND d.doc_id = ?"
        args = (doc_id,)
    q += " ORDER BY d.ingested_at, p.page_no"
    return conn.execute(q, args).fetchall()


def mark_document_extracted(conn: Connection, doc_id: str) -> None:
    conn.execute(
        "UPDATE documents SET status='extracted' WHERE doc_id=? AND"
        " status='ingested'",
        (doc_id,),
    )
