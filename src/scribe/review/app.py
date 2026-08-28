"""Local single-user workbench UI (PRD 9, extended).

FastAPI serving one HTML page plus a small JSON API. Binds to loopback only.
Three concerns in one page: ingest (upload or server path), run (background
extraction with a live event feed), and review (flagged-field queue).
Corrections are validated against the field definition before being accepted,
so the review step cannot introduce a value the schema would reject.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from scribe.config import Config
from scribe.review.runs import RunManager
from scribe.schema import Schema, find_schema, list_schemas
from scribe.stages.export import (
    UnresolvedFlagsError,
    finalize_document,
    unresolved_flags,
)
from scribe.stages.validate import coerce_value

STATIC_DIR = Path(__file__).parent / "static"


class ReviewIn(BaseModel):
    action: str                       # accept | correct | reject
    corrected_value: Any = None       # already-typed JSON value
    comment: str | None = None
    reviewer: str = "operator"


class IngestPathIn(BaseModel):
    path: str
    schema_id: str | None = None


class RunIn(BaseModel):
    doc_id: str | None = None         # None = every pending page
    schema_id: str | None = None      # fallback for docs bound without one


def create_app(conn: Connection, cfg: Config) -> FastAPI:
    app = FastAPI(title="scribe review", docs_url=None, redoc_url=None)
    schemas: dict[str, Schema] = {}
    runs = RunManager(conn, cfg)

    def schema_for_doc(doc_id: str) -> Schema:
        row = conn.execute(
            "SELECT schema_id FROM documents WHERE doc_id=?", (doc_id,)
        ).fetchone()
        if not row or not row["schema_id"]:
            raise HTTPException(400, f"document {doc_id} has no schema bound")
        sid = row["schema_id"]
        if sid not in schemas:
            schemas[sid] = find_schema(sid)
        return schemas[sid]

    # -- page ---------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC_DIR / "index.html").read_text()

    # -- queue + item -------------------------------------------------------

    @app.get("/api/queue")
    def queue(doc: str | None = None, field: str | None = None) -> list[dict]:
        q = "SELECT * FROM review_queue"
        conds, args = [], []
        if doc:
            conds.append("doc_id = ?")
            args.append(doc)
        if field:
            conds.append("field_name = ?")
            args.append(field)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY doc_id, page_no, field_name"
        out = []
        for r in conn.execute(q, args):
            d = dict(r)
            d["value"] = json.loads(d["value"]) if d["value"] else None
            out.append(d)
        return out

    @app.get("/api/item/{extraction_id}")
    def item(extraction_id: str) -> dict:
        r = conn.execute(
            "SELECT e.*, p.doc_id, p.page_no, p.image_path,"
            " p.width_px, p.height_px, r.bbox FROM extractions e"
            " JOIN pages p USING (page_id)"
            " LEFT JOIN regions r USING (region_id)"
            " WHERE e.extraction_id=?",
            (extraction_id,),
        ).fetchone()
        if not r:
            raise HTTPException(404, "no such extraction")
        d = dict(r)
        d["value"] = json.loads(d["value"]) if d["value"] else None
        d["validation_errors"] = json.loads(d["validation_errors"] or "[]")
        d["bbox"] = json.loads(d["bbox"]) if d["bbox"] else None
        schema = schema_for_doc(d["doc_id"])
        try:
            fd = schema.field(d["field_name"])
            d["field_def"] = fd.model_dump(exclude_none=True)
        except KeyError:
            d["field_def"] = None
        return d

    @app.get("/api/page-fields/{page_id}")
    def page_fields(page_id: str) -> list[dict]:
        """Every extraction on a page with its review state, for the
        progress chips in the review UI."""
        return [dict(r) for r in conn.execute(
            "SELECT e.extraction_id, e.field_name, e.flagged,"
            " (SELECT r.action FROM reviews r WHERE r.extraction_id ="
            "  e.extraction_id ORDER BY r.reviewed_at DESC LIMIT 1)"
            "  AS review_action"
            " FROM extractions e WHERE e.page_id = ?"
            " ORDER BY e.field_name",
            (page_id,),
        )]

    @app.get("/api/row-guides/{extraction_id}")
    def row_guides(extraction_id: str) -> dict:
        """Detected horizontal ruled lines of the image shown for an
        extraction, as fractions of image height. Best effort: an empty list
        means no usable line structure was found."""
        r = conn.execute(
            "SELECT e.crop_path, p.image_path FROM extractions e"
            " JOIN pages p USING (page_id) WHERE e.extraction_id=?",
            (extraction_id,),
        ).fetchone()
        if not r:
            raise HTTPException(404, "no such extraction")
        from scribe.review.guides import detect_row_lines

        path = Path(r["crop_path"] or r["image_path"])
        return {"ys": detect_row_lines(path)}

    @app.get("/api/page-image/{page_id}")
    def page_image(page_id: str):
        r = conn.execute(
            "SELECT image_path FROM pages WHERE page_id=?", (page_id,)
        ).fetchone()
        if not r:
            raise HTTPException(404, "no such page")
        return FileResponse(r["image_path"], media_type="image/png")

    @app.get("/api/crop/{extraction_id}")
    def crop(extraction_id: str):
        r = conn.execute(
            "SELECT crop_path, page_id FROM extractions WHERE extraction_id=?",
            (extraction_id,),
        ).fetchone()
        if not r:
            raise HTTPException(404, "no such extraction")
        if r["crop_path"]:
            return FileResponse(r["crop_path"], media_type="image/png")
        # Whole-page mode: the "crop" is the page (PRD 10.1).
        return page_image(r["page_id"])

    # -- review actions -------------------------------------------------------

    @app.post("/api/review/{extraction_id}")
    def review(extraction_id: str, body: ReviewIn) -> dict:
        r = conn.execute(
            "SELECT e.*, p.doc_id FROM extractions e JOIN pages p USING (page_id)"
            " WHERE e.extraction_id=?",
            (extraction_id,),
        ).fetchone()
        if not r:
            raise HTTPException(404, "no such extraction")
        if body.action not in ("accept", "correct", "reject"):
            raise HTTPException(400, "action must be accept|correct|reject")

        corrected_json = None
        if body.action == "correct":
            schema = schema_for_doc(r["doc_id"])
            try:
                fd = schema.field(r["field_name"])
            except KeyError:
                raise HTTPException(
                    400, f"field {r['field_name']} is not in the schema"
                ) from None
            coerced, errors = coerce_value(body.corrected_value, fd)
            if errors:
                raise HTTPException(422, "; ".join(errors))
            if coerced is None and fd.required:
                raise HTTPException(
                    422, f"{fd.name} is required; use reject to null it"
                    " deliberately"
                )
            corrected_json = json.dumps(coerced, ensure_ascii=False)

        review_id = uuid.uuid4().hex[:16]
        conn.execute(
            "INSERT INTO reviews (review_id, extraction_id, reviewer, action,"
            " corrected_value, comment, reviewed_at) VALUES (?,?,?,?,?,?,?)",
            (review_id, extraction_id, body.reviewer, body.action,
             corrected_json, body.comment,
             datetime.now(timezone.utc).isoformat()),
        )
        return {"review_id": review_id, "action": body.action}

    # -- documents + finalize --------------------------------------------------

    @app.get("/api/docs")
    def docs() -> list[dict]:
        out = []
        for r in conn.execute(
            "SELECT d.doc_id, d.source_path, d.status, d.page_count,"
            " d.schema_id,"
            " COUNT(e.extraction_id) AS n_extractions,"
            " SUM(e.flagged) AS n_flagged"
            " FROM documents d"
            " LEFT JOIN pages p USING (doc_id)"
            " LEFT JOIN extractions e USING (page_id)"
            " GROUP BY d.doc_id ORDER BY d.ingested_at"
        ):
            d = dict(r)
            d["source_name"] = Path(d.pop("source_path")).name
            d["unresolved"] = len(unresolved_flags(conn, d["doc_id"]))
            out.append(d)
        return out

    @app.post("/api/finalize/{doc_id}")
    def finalize(doc_id: str) -> dict:
        schema = schema_for_doc(doc_id)
        try:
            record_id = finalize_document(conn, doc_id, schema)
        except UnresolvedFlagsError as e:
            raise HTTPException(409, str(e)) from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return {"record_id": record_id}

    # -- ingest ---------------------------------------------------------------

    @app.get("/api/schemas")
    def schemas_list() -> list[dict]:
        return [
            {"schema_id": s.schema_id, "version": s.version,
             "n_fields": len(s.fields)}
            for _p, s in list_schemas()
        ]

    def _check_schema(schema_id: str | None) -> None:
        if schema_id:
            try:
                find_schema(schema_id)
            except KeyError as e:
                raise HTTPException(400, e.args[0]) from None

    def _ingest_summary(res) -> dict:
        return {
            "ingested": res.ingested,
            "duplicates": [Path(p).name for p in res.skipped_duplicate],
            "unsupported": [Path(p).name for p in res.skipped_unsupported],
            "failed": [{"file": Path(p).name, "error": err}
                       for p, err in res.failed],
        }

    @app.post("/api/upload")
    async def upload(
        files: list[UploadFile] = File(...),
        schema_id: str | None = Form(None),
    ) -> dict:
        from scribe.stages.ingest import IngestResult, ingest_file

        _check_schema(schema_id)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = Path(cfg.paths.inbox) / f"upload_{stamp}"
        dest.mkdir(parents=True, exist_ok=True)
        res = IngestResult()
        for f in files:
            name = Path(f.filename or "upload").name   # strip any path part
            target = dest / name
            target.write_bytes(await f.read())
            try:
                doc_id = ingest_file(conn, cfg, target, schema_id)
            except Exception as e:  # noqa: BLE001 -- report per file
                res.failed.append((str(target), str(e)))
                continue
            if doc_id is None:
                res.skipped_duplicate.append(str(target))
                target.unlink(missing_ok=True)   # already have these bytes
            else:
                res.ingested.append(doc_id)
        if not any(dest.iterdir()):
            dest.rmdir()
        return _ingest_summary(res)

    @app.post("/api/ingest")
    def ingest_server_path(body: IngestPathIn) -> dict:
        from scribe.stages.ingest import ingest_path

        _check_schema(body.schema_id)
        path = Path(body.path).expanduser()
        if not path.exists():
            raise HTTPException(400, f"{path} does not exist")
        return _ingest_summary(ingest_path(conn, cfg, path, body.schema_id))

    @app.post("/api/purge/{doc_id}")
    def purge(doc_id: str) -> dict:
        from scribe.stages.ingest import purge_document

        if not purge_document(conn, cfg, doc_id):
            raise HTTPException(404, f"no document with id {doc_id}")
        return {"purged": doc_id}

    # -- run ------------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict:
        from scribe.engines import build_extraction_engine, build_layout_engine
        from scribe.engines.registry import build_verify_engine

        def probe(build):
            try:
                eng = build()
                if eng is None:
                    return None
                h = eng.health()
                return {"ok": h.ok, "backend": h.backend, "model": h.model,
                        "detail": h.detail, "latency_ms": h.latency_ms,
                        "name": getattr(eng, "name", h.backend)}
            except Exception as e:  # noqa: BLE001 -- health must not 500
                return {"ok": False, "detail": str(e)}

        return {
            "extraction": probe(lambda: build_extraction_engine(cfg)),
            "verify": probe(lambda: build_verify_engine(cfg)),
            "layout": probe(lambda: build_layout_engine(cfg)),
        }

    @app.post("/api/run")
    def run_start(body: RunIn) -> dict:
        ok, msg = runs.start(body.doc_id, body.schema_id)
        if not ok:
            raise HTTPException(409, msg)
        return {"status": msg}

    @app.get("/api/run/status")
    def run_status(since: int = 0) -> dict:
        return runs.status(since)

    # -- browse extractions ---------------------------------------------------

    @app.get("/api/extractions")
    def extractions(doc: str) -> list[dict]:
        rows = conn.execute(
            "SELECT e.extraction_id, e.page_id, p.page_no, e.field_name,"
            " e.value, e.raw_transcription, e.note, e.composite_confidence,"
            " e.validation_status, e.flagged, e.flag_reason, e.latency_ms,"
            " p.width_px, p.height_px, rg.bbox,"
            " (SELECT r.action FROM reviews r WHERE r.extraction_id ="
            "  e.extraction_id ORDER BY r.reviewed_at DESC LIMIT 1)"
            "  AS review_action"
            " FROM extractions e JOIN pages p USING (page_id)"
            " LEFT JOIN regions rg USING (region_id)"
            " WHERE p.doc_id = ? ORDER BY p.page_no, e.field_name",
            (doc,),
        )
        out = []
        for r in rows:
            d = dict(r)
            d["value"] = json.loads(d["value"]) if d["value"] else None
            d["bbox"] = json.loads(d["bbox"]) if d["bbox"] else None
            out.append(d)
        return out

    return app
