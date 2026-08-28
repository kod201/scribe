"""Workbench API tests: schema listing, upload/path ingest, run guard,
extraction browsing, purge. Nothing here needs a model server."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from scribe.config import Config, ExtractionEngineConfig
from scribe.db import init_db
from scribe.review.app import create_app
from tests.test_export import add_extraction


@pytest.fixture()
def wb(tmp_path):
    cfg = Config(extraction_engine=ExtractionEngineConfig(model="fake"))
    cfg.paths.inbox = tmp_path / "inbox"
    cfg.paths.work = tmp_path / "work"
    cfg.paths.db = tmp_path / "db.sqlite"
    cfg.ingest.denoise = False
    cfg.paths.mkdirs()
    conn = init_db(cfg.paths.db)
    return TestClient(create_app(conn, cfg)), conn, cfg, tmp_path


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), (246, 246, 244)).save(buf, "PNG")
    return buf.getvalue()


def test_schemas_listed(wb):
    c, *_ = wb
    ids = {s["schema_id"] for s in c.get("/api/schemas").json()}
    assert "amr_flow_v1" in ids


def test_upload_ingests_and_dedupes(wb):
    c, conn, cfg, _ = wb
    png = _png_bytes()
    r = c.post("/api/upload",
               files=[("files", ("page.png", png, "image/png"))],
               data={"schema_id": "amr_flow_v1"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["ingested"]) == 1 and not body["failed"]
    doc = conn.execute("SELECT * FROM documents").fetchone()
    assert doc["schema_id"] == "amr_flow_v1" and doc["page_count"] == 1

    # Same bytes again -> duplicate, and the copy is cleaned up.
    r2 = c.post("/api/upload",
                files=[("files", ("page.png", png, "image/png"))])
    assert r2.json()["duplicates"] == ["page.png"]
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1


def test_upload_rejects_unknown_schema(wb):
    c, *_ = wb
    r = c.post("/api/upload",
               files=[("files", ("page.png", _png_bytes(), "image/png"))],
               data={"schema_id": "nope_v9"})
    assert r.status_code == 400


def test_ingest_server_path(wb):
    c, conn, cfg, tmp_path = wb
    src = tmp_path / "batch"
    src.mkdir()
    (src / "a.png").write_bytes(_png_bytes())
    r = c.post("/api/ingest", json={"path": str(src),
                                    "schema_id": "amr_flow_v1"})
    assert r.status_code == 200 and len(r.json()["ingested"]) == 1
    r2 = c.post("/api/ingest", json={"path": str(tmp_path / "missing")})
    assert r2.status_code == 400


def test_run_status_idle_and_extractions_browse(wb):
    c, conn, cfg, tmp_path = wb
    s = c.get("/api/run/status").json()
    assert s["running"] is False and s["events"] == []

    from scribe.stages.ingest import ingest_file
    img = tmp_path / "p.png"
    img.write_bytes(_png_bytes())
    doc_id = ingest_file(conn, cfg, img, schema_id="amr_flow_v1")
    page_id = conn.execute("SELECT page_id FROM pages").fetchone()[0]
    add_extraction(conn, page_id, "patient_name", "X")
    add_extraction(conn, page_id, "patient_age_years", None,
                   flagged=True, reason="illegible")

    rows = c.get("/api/extractions", params={"doc": doc_id}).json()
    assert {r["field_name"] for r in rows} == {
        "patient_name", "patient_age_years"}
    flagged = next(r for r in rows if r["flagged"])
    assert flagged["review_action"] is None

    c.post(f"/api/review/{flagged['extraction_id']}",
           json={"action": "accept"})
    rows = c.get("/api/extractions", params={"doc": doc_id}).json()
    assert next(r for r in rows if r["flagged"])["review_action"] == "accept"


def test_purge_endpoint(wb):
    c, conn, cfg, tmp_path = wb
    from scribe.stages.ingest import ingest_file
    img = tmp_path / "p.png"
    img.write_bytes(_png_bytes())
    doc_id = ingest_file(conn, cfg, img, schema_id="amr_flow_v1")
    assert c.post(f"/api/purge/{doc_id}").status_code == 200
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    assert c.post(f"/api/purge/{doc_id}").status_code == 404


def test_health_reports_unreachable_engine(wb):
    c, *_ = wb
    h = c.get("/api/health").json()
    assert h["extraction"]["ok"] is False   # no server on the fake URL


def test_guides_detect_ruled_lines(tmp_path):
    import numpy as np
    from PIL import Image as PILImage

    from scribe.review.guides import detect_row_lines

    img = np.full((600, 800, 3), 240, np.uint8)
    for y in range(100, 560, 40):          # 12 evenly spaced rules
        img[y:y + 2, 20:780] = 90
    p = tmp_path / "ruled.png"
    PILImage.fromarray(img).save(p)
    ys = detect_row_lines(p)
    assert 10 <= len(ys) <= 13
    assert all(0 < y < 1 for y in ys)
    assert ys == sorted(ys)

    blank = tmp_path / "blank.png"
    PILImage.fromarray(np.full((600, 800, 3), 240, np.uint8)).save(blank)
    assert detect_row_lines(blank) == []


def test_item_bbox_page_fields_and_row_guides(wb):
    c, conn, cfg, tmp_path = wb
    from scribe.stages.ingest import ingest_file
    img = tmp_path / "p.png"
    img.write_bytes(_png_bytes())
    doc_id = ingest_file(conn, cfg, img, schema_id="amr_flow_v1")
    page_id = conn.execute("SELECT page_id FROM pages").fetchone()[0]
    eid = add_extraction(conn, page_id, "patient_age_years", None,
                         flagged=True)
    add_extraction(conn, page_id, "patient_name", "X")

    d = c.get(f"/api/item/{eid}").json()
    assert d["bbox"] is None and d["width_px"] == 400

    pf = c.get(f"/api/page-fields/{page_id}").json()
    assert {f["field_name"] for f in pf} == {
        "patient_age_years", "patient_name"}
    assert all(f["review_action"] is None for f in pf)
    c.post(f"/api/review/{eid}", json={"action": "accept"})
    pf = c.get(f"/api/page-fields/{page_id}").json()
    assert next(f for f in pf if f["extraction_id"] == eid)[
        "review_action"] == "accept"

    g = c.get(f"/api/row-guides/{eid}").json()
    assert g["ys"] == []                       # plain page, no rules
    assert c.get("/api/row-guides/nope").status_code == 404
