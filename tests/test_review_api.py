"""Review API tests: queue, corrections are schema-validated, finalize gates."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from scribe.config import Config, ExtractionEngineConfig
from scribe.db import init_db
from scribe.review.app import create_app
from scribe.stages.ingest import ingest_file
from tests.test_export import add_extraction  # reuse the row factory


@pytest.fixture()
def client(tmp_path):
    cfg = Config(extraction_engine=ExtractionEngineConfig(model="fake"))
    cfg.paths.work = tmp_path / "work"
    cfg.paths.db = tmp_path / "db.sqlite"
    cfg.ingest.denoise = False
    conn = init_db(cfg.paths.db)
    img = tmp_path / "page.png"
    Image.new("RGB", (400, 300), (246, 246, 244)).save(img)
    doc_id = ingest_file(conn, cfg, img, schema_id="amr_flow_v1")
    page_id = conn.execute("SELECT page_id FROM pages").fetchone()[0]
    return TestClient(create_app(conn, cfg)), conn, doc_id, page_id


def test_index_serves_page(client):
    c, *_ = client
    r = c.get("/")
    assert r.status_code == 200 and "scribe review" in r.text


def test_queue_lists_only_unreviewed_flags(client):
    c, conn, doc_id, page_id = client
    add_extraction(conn, page_id, "patient_name", "X")                # unflagged
    eid = add_extraction(conn, page_id, "patient_age_years", None,
                         flagged=True, reason="coercion failed")
    q = c.get("/api/queue").json()
    assert [i["extraction_id"] for i in q] == [eid]

    c.post(f"/api/review/{eid}", json={"action": "accept"})
    assert c.get("/api/queue").json() == []


def test_item_includes_field_def(client):
    c, conn, doc_id, page_id = client
    eid = add_extraction(conn, page_id, "patient_age_years", None, flagged=True)
    d = c.get(f"/api/item/{eid}").json()
    assert d["field_def"]["type"] == "integer"
    assert d["field_def"]["max"] == 120


def test_correction_is_schema_validated(client):
    c, conn, doc_id, page_id = client
    eid = add_extraction(conn, page_id, "patient_age_years", None, flagged=True)

    r = c.post(f"/api/review/{eid}",
               json={"action": "correct", "corrected_value": "Ad"})
    assert r.status_code == 422           # still not an integer

    r = c.post(f"/api/review/{eid}",
               json={"action": "correct", "corrected_value": 200})
    assert r.status_code == 422           # above max

    r = c.post(f"/api/review/{eid}",
               json={"action": "correct", "corrected_value": 34})
    assert r.status_code == 200
    stored = conn.execute("SELECT corrected_value FROM reviews").fetchone()[0]
    assert json.loads(stored) == 34


def test_table_correction_roundtrips(client):
    c, conn, doc_id, page_id = client
    eid = add_extraction(conn, page_id, "medications", None, flagged=True)
    rows = [{"drug_name": "Tab Paracetamol", "dose": "500mg",
             "frequency": "qds", "duration": "x 5/7"}]
    r = c.post(f"/api/review/{eid}",
               json={"action": "correct", "corrected_value": rows})
    assert r.status_code == 200


def test_finalize_gates_on_unresolved_flags(client):
    c, conn, doc_id, page_id = client
    eid = add_extraction(conn, page_id, "patient_name", "X",
                         flagged=True, reason="low confidence")
    r = c.post(f"/api/finalize/{doc_id}")
    assert r.status_code == 409

    c.post(f"/api/review/{eid}", json={"action": "accept"})
    r = c.post(f"/api/finalize/{doc_id}")
    assert r.status_code == 200 and r.json()["record_id"]

    docs = c.get("/api/docs").json()
    assert docs[0]["status"] == "finalized"


def test_crop_falls_back_to_page_image(client):
    c, conn, doc_id, page_id = client
    eid = add_extraction(conn, page_id, "patient_name", "X", flagged=True)
    r = c.get(f"/api/crop/{eid}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
