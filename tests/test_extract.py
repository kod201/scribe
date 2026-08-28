"""Extract-stage tests with a scripted fake engine -- no model, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from scribe.config import Config, ExtractionEngineConfig
from scribe.db import init_db
from scribe.engines.base import EngineHealth, ExtractionEngine, RawCompletion
from scribe.prompts import PROMPT_VERSION
from scribe.schema import load_schema
from scribe.stages.extract import extract_field, extract_page, pages_to_extract
from scribe.stages.ingest import ingest_file

SCHEMA = load_schema("schemas/amr_flow_v1.yaml")


class FakeEngine(ExtractionEngine):
    """Returns queued responses; records every prompt it was asked."""

    name = "fake"
    version = "test"
    model = "fake-model"

    def __init__(self, responses: list[str] | None = None,
                 default: str | None = None):
        self.responses = list(responses or [])
        self.default = default
        self.calls: list[dict] = []

    def health(self) -> EngineHealth:
        return EngineHealth(ok=True, backend="fake", detail="fake")

    def complete(self, *, system, user, images, json_schema=None,
                 max_tokens=None, temperature=None) -> RawCompletion:
        self.calls.append({"user": user, "images": images})
        text = self.responses.pop(0) if self.responses else (self.default or "{}")
        return RawCompletion(text=text, model="fake-model", latency_ms=1.0)


def env(value, legible=True, conf=0.95, raw=None, note=None) -> str:
    return json.dumps({
        "value": value, "legible": legible, "confidence": conf,
        "raw_transcription": raw if raw is not None else str(value),
        "note": note,
    })


@pytest.fixture()
def cfg(tmp_path: Path) -> Config:
    c = Config(extraction_engine=ExtractionEngineConfig(model="fake"))
    c.paths.work = tmp_path / "work"
    c.paths.db = tmp_path / "db.sqlite"
    c.ingest.denoise = False
    return c


@pytest.fixture()
def page(cfg, tmp_path):
    conn = init_db(cfg.paths.db)
    img = tmp_path / "page.png"
    Image.new("RGB", (800, 600), (246, 246, 244)).save(img)
    ingest_file(conn, cfg, img)
    return conn, conn.execute("SELECT * FROM pages").fetchone()


IMG = Path("samples/flow/images/SYN_001.png")
AGE = SCHEMA.field("patient_age_years")


class TestExtractField:
    def test_clean_response(self):
        eng = FakeEngine([env(34, raw="34")])
        fx = extract_field(eng, SCHEMA, AGE, IMG, 0.85)
        assert fx.value == 34 and not fx.flagged
        assert fx.validation_status == "pass"

    def test_repair_retry_recovers(self):
        eng = FakeEngine(["utter garbage not json", env(34, raw="34")])
        fx = extract_field(eng, SCHEMA, AGE, IMG, 0.85)
        assert fx.value == 34 and not fx.flagged
        assert len(eng.calls) == 2
        assert "not valid JSON" in eng.calls[1]["user"]

    def test_double_failure_flags_unparsed(self):
        eng = FakeEngine(["garbage", "more garbage"])
        fx = extract_field(eng, SCHEMA, AGE, IMG, 0.85)
        assert fx.value is None
        assert fx.validation_status == "unparsed"
        assert fx.flagged and "unparseable" in fx.flag_reason
        assert len(eng.calls) == 2

    def test_ad_age_is_flagged_not_stored(self):
        eng = FakeEngine([env("Ad", raw="Ad", conf=0.8)])
        fx = extract_field(eng, SCHEMA, AGE, IMG, 0.85)
        assert fx.value is None
        assert fx.raw_transcription == "Ad"    # faithful reading preserved
        assert fx.flagged and fx.validation_status == "fail"

    def test_missing_envelope_keys_do_not_crash(self):
        eng = FakeEngine(['{"value": 34}'])
        fx = extract_field(eng, SCHEMA, AGE, IMG, 0.85)
        # legible missing -> False -> flagged as illegible; still no crash.
        assert fx.value == 34
        assert fx.flagged


class TestExtractPage:
    def _responses_for(self, page_type: str, values: dict) -> list[str]:
        """document_type first, then fields_for(page_type) in schema order."""
        out = [env(page_type, raw=page_type)]
        for fd in SCHEMA.fields_for(page_type):
            if fd.name == "document_type":
                continue
            v = values.get(fd.name)
            out.append(env(v, raw=json.dumps(v)))
        return out

    def test_classification_sets_page_type_and_scopes_fields(self, cfg, page):
        conn, row = page
        eng = FakeEngine(
            self._responses_for("visit_note", {
                "patient_name": "Chinedu Okafor", "patient_age_years": 28,
                "patient_sex": "male", "hospital_number": "MED/001/26",
                "document_date": "23/03/2026",
                "chief_complaint": "Burning chest pain",
                "assessment": "Likely GERD", "plan": "Omeprazole",
            })
        )
        extract_page(conn, cfg, eng, SCHEMA, row)

        assert conn.execute("SELECT page_type FROM pages").fetchone()[0] == \
            "visit_note"
        names = {r[0] for r in conn.execute(
            "SELECT field_name FROM extractions")}
        expected = {f.name for f in SCHEMA.fields_for("visit_note")}
        assert names == expected
        # No prescription/lab/vitals fields were ever asked.
        assert "medications" not in names and "vitals" not in names

    def test_rerun_is_idempotent(self, cfg, page):
        conn, row = page
        vals = {"patient_name": "X", "patient_age_years": 28,
                "patient_sex": "male", "hospital_number": "1",
                "document_date": "23/03/2026", "chief_complaint": "c",
                "assessment": "a", "plan": "p"}
        eng = FakeEngine(self._responses_for("visit_note", vals))
        extract_page(conn, cfg, eng, SCHEMA, row)
        first = conn.execute("SELECT COUNT(*) FROM extractions").fetchone()[0]

        eng2 = FakeEngine(default=env("SHOULD NOT BE ASKED"))
        row2 = conn.execute("SELECT * FROM pages").fetchone()
        extract_page(conn, cfg, eng2, SCHEMA, row2)
        assert eng2.calls == []
        assert conn.execute("SELECT COUNT(*) FROM extractions").fetchone()[0] == first

    def test_cross_field_rule_failure_flags_fields(self, cfg, page):
        conn, row = page
        # A prescription page whose medications list comes back empty.
        vals = {"patient_name": "X", "patient_age_years": 30,
                "patient_sex": "female", "hospital_number": "1",
                "document_date": "23/03/2026", "prescriber_name": "Dr A",
                "prescription_diagnosis": "Malaria", "medications": []}
        eng = FakeEngine(self._responses_for("prescription", vals))
        extract_page(conn, cfg, eng, SCHEMA, row)

        med = conn.execute(
            "SELECT flagged, flag_reason FROM extractions"
            " WHERE field_name='medications'").fetchone()
        assert med["flagged"] == 1
        assert "cross-field" in med["flag_reason"]

    def test_flagged_fields_reach_review_queue(self, cfg, page):
        conn, row = page
        vals = {"patient_name": None, "patient_age_years": "Ad",
                "patient_sex": "male", "hospital_number": "5830682",
                "document_date": "12/05/2026", "requesting_doctor": None,
                "specimen_type": "sputum", "lab_priority": None,
                "lab_clinical_details": "?? TB",
                "tests_requested": [{"test_name": "GeneXpert"}]}
        eng = FakeEngine(self._responses_for("lab_request", vals))
        extract_page(conn, cfg, eng, SCHEMA, row)

        queue = {r["field_name"] for r in conn.execute(
            "SELECT field_name FROM review_queue")}
        assert "patient_age_years" in queue      # coercion failure
        rows_all = conn.execute("SELECT COUNT(*) FROM extractions").fetchone()[0]
        assert rows_all == len(SCHEMA.fields_for("lab_request"))


class TestPagesToExtract:
    def test_doc_filter(self, cfg, page):
        conn, row = page
        assert len(pages_to_extract(conn)) == 1
        assert len(pages_to_extract(conn, doc_id=row["doc_id"])) == 1
        assert pages_to_extract(conn, doc_id="nope") == []


class TestDefaultPageTypeFallback:
    def test_null_classification_routes_to_default(self, cfg, page):
        conn, row = page
        schema = SCHEMA.model_copy(
            update={"default_page_type": "vitals_chart"})
        # Classifier refuses (null), then only vitals_chart fields should
        # run: global fields + the vitals-specific ones, nothing else.
        eng = FakeEngine(
            [env(None, legible=False, note="I cannot process this request.")],
            default=env(None, legible=True),
        )
        extract_page(conn, cfg, eng, schema, row)
        extracted = {
            r["field_name"] for r in
            conn.execute("SELECT field_name FROM extractions")
        }
        expected = {f.name for f in schema.fields_for("vitals_chart")}
        assert extracted == expected
        pt = conn.execute(
            "SELECT page_type FROM pages WHERE page_id=?",
            (row["page_id"],),
        ).fetchone()["page_type"]
        assert pt == "vitals_chart"

    def test_no_default_keeps_run_everything(self, cfg, page):
        conn, row = page
        eng = FakeEngine(
            [env(None, legible=False)], default=env(None, legible=True),
        )
        extract_page(conn, cfg, eng, SCHEMA, row)
        extracted = {
            r["field_name"] for r in
            conn.execute("SELECT field_name FROM extractions")
        }
        assert extracted == {f.name for f in SCHEMA.fields}

    def test_unknown_default_page_type_rejected(self):
        data = SCHEMA.model_dump()
        data["default_page_type"] = "nope"
        with pytest.raises(ValueError, match="default_page_type"):
            type(SCHEMA).model_validate(data)
