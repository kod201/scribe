"""Finalize + export tests: the provenance rule is the contract under test.

PRD 8: a value in `records` must trace to exactly one `extractions` row (and a
`reviews` row if it was flagged). PRD 5.1: nothing low-confidence reaches the
sink unreviewed.
"""

from __future__ import annotations

import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image

from scribe.config import Config, ExtractionEngineConfig
from scribe.db import init_db
from scribe.schema import load_schema
from scribe.stages.export import (
    UnresolvedFlagsError,
    export_csv,
    export_jsonl,
    finalize_document,
    unresolved_flags,
)
from scribe.stages.ingest import ingest_file

SCHEMA = load_schema("schemas/amr_flow_v1.yaml")


@pytest.fixture()
def db(tmp_path):
    cfg = Config(extraction_engine=ExtractionEngineConfig(model="fake"))
    cfg.paths.work = tmp_path / "work"
    cfg.paths.db = tmp_path / "db.sqlite"
    cfg.ingest.denoise = False
    conn = init_db(cfg.paths.db)
    img = tmp_path / "page.png"
    Image.new("RGB", (400, 300), (246, 246, 244)).save(img)
    doc_id = ingest_file(conn, cfg, img)
    page_id = conn.execute("SELECT page_id FROM pages").fetchone()[0]
    return conn, doc_id, page_id


def add_extraction(conn, page_id, field_name, value, flagged=False,
                   reason=None) -> str:
    eid = uuid.uuid4().hex[:16]
    conn.execute(
        "INSERT INTO extractions (extraction_id, page_id, field_name, value,"
        " raw_transcription, legible, model_confidence, composite_confidence,"
        " validation_status, flagged, flag_reason, model_name, prompt_version,"
        " created_at) VALUES (?,?,?,?,?,1,0.9,0.9,'pass',?,?,'fake','v1',?)",
        (eid, page_id, field_name, json.dumps(value), str(value),
         int(flagged), reason, datetime.now(timezone.utc).isoformat()),
    )
    return eid


def add_review(conn, extraction_id, action, corrected=None) -> str:
    rid = uuid.uuid4().hex[:16]
    conn.execute(
        "INSERT INTO reviews (review_id, extraction_id, reviewer, action,"
        " corrected_value, reviewed_at) VALUES (?,?,?,?,?,?)",
        (rid, extraction_id, "tester", action,
         None if corrected is None else json.dumps(corrected),
         datetime.now(timezone.utc).isoformat()),
    )
    return rid


class TestFinalize:
    def test_refuses_with_unresolved_flags(self, db):
        conn, doc_id, page_id = db
        add_extraction(conn, page_id, "patient_age_years", None,
                       flagged=True, reason="coercion failed")
        assert unresolved_flags(conn, doc_id) == ["patient_age_years"]
        with pytest.raises(UnresolvedFlagsError):
            finalize_document(conn, doc_id, SCHEMA)
        assert conn.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0

    def test_accept_keeps_model_value(self, db):
        conn, doc_id, page_id = db
        eid = add_extraction(conn, page_id, "patient_name", "J.D",
                             flagged=True, reason="low confidence")
        rid = add_review(conn, eid, "accept")
        finalize_document(conn, doc_id, SCHEMA)
        rec = conn.execute("SELECT * FROM records").fetchone()
        final = json.loads(rec["final_json"])
        assert final["patient_name"] == "J.D"
        prov = json.loads(rec["provenance"])
        assert prov["patient_name"] == {"extraction_id": eid, "review_id": rid}

    def test_correct_updates_record_not_extraction(self, db):
        conn, doc_id, page_id = db
        eid = add_extraction(conn, page_id, "patient_age_years", None,
                             flagged=True, reason="coercion failed")
        add_review(conn, eid, "correct", corrected=34)
        finalize_document(conn, doc_id, SCHEMA)
        final = json.loads(
            conn.execute("SELECT final_json FROM records").fetchone()[0])
        assert final["patient_age_years"] == 34
        # The extraction row still says what the model said.
        stored = conn.execute(
            "SELECT value FROM extractions WHERE extraction_id=?", (eid,)
        ).fetchone()[0]
        assert json.loads(stored) is None

    def test_reject_nulls_the_field(self, db):
        conn, doc_id, page_id = db
        eid = add_extraction(conn, page_id, "patient_name", "Halluci Nation",
                             flagged=True, reason="low confidence")
        add_review(conn, eid, "reject")
        finalize_document(conn, doc_id, SCHEMA)
        final = json.loads(
            conn.execute("SELECT final_json FROM records").fetchone()[0])
        assert final["patient_name"] is None

    def test_unflagged_fields_finalize_without_review(self, db):
        conn, doc_id, page_id = db
        eid = add_extraction(conn, page_id, "hospital_number", "2026/SC/015")
        finalize_document(conn, doc_id, SCHEMA)
        rec = conn.execute("SELECT * FROM records").fetchone()
        prov = json.loads(rec["provenance"])
        assert prov["hospital_number"]["extraction_id"] == eid
        assert prov["hospital_number"]["review_id"] is None
        assert conn.execute(
            "SELECT status FROM documents").fetchone()[0] == "finalized"

    def test_every_final_value_has_provenance(self, db):
        conn, doc_id, page_id = db
        add_extraction(conn, page_id, "patient_name", "A")
        add_extraction(conn, page_id, "hospital_number", "1")
        finalize_document(conn, doc_id, SCHEMA)
        rec = conn.execute("SELECT * FROM records").fetchone()
        final = json.loads(rec["final_json"])
        prov = json.loads(rec["provenance"])
        assert set(final) == set(prov)          # no orphan values (PRD 8)


class TestExport:
    def _finalized(self, db):
        conn, doc_id, page_id = db
        add_extraction(conn, page_id, "patient_name", "J.D")
        add_extraction(conn, page_id, "patient_age_years", 34)
        add_extraction(conn, page_id, "medications",
                       [{"drug_name": "Tab X", "dose": "500mg",
                         "frequency": "bd", "duration": None}])
        finalize_document(conn, doc_id, SCHEMA)
        return conn

    def test_csv_roundtrip(self, db, tmp_path):
        conn = self._finalized(db)
        out = tmp_path / "out.csv"
        assert export_csv(conn, out) == 1
        rows = list(csv.DictReader(out.read_text().splitlines()))
        assert rows[0]["patient_name"] == "J.D"
        assert rows[0]["patient_age_years"] == "34"
        meds = json.loads(rows[0]["medications"])
        assert meds[0]["drug_name"] == "Tab X"

    def test_jsonl_roundtrip(self, db, tmp_path):
        conn = self._finalized(db)
        out = tmp_path / "out.jsonl"
        assert export_jsonl(conn, out) == 1
        rec = json.loads(out.read_text().splitlines()[0])
        assert rec["fields"]["patient_age_years"] == 34

    def test_export_marks_records(self, db, tmp_path):
        conn = self._finalized(db)
        export_csv(conn, tmp_path / "out.csv")
        row = conn.execute(
            "SELECT exported_at, export_target FROM records").fetchone()
        assert row["exported_at"] and "out.csv" in row["export_target"]


