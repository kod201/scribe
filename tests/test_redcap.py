"""REDCap adapter tests against a mock transport -- wire format, consent
gating, token handling, count verification. Real-project verification is the
M5 exit criterion and happens on the deployment box."""

from __future__ import annotations

import json
import urllib.parse

import httpx
import pytest
from PIL import Image

from scribe.config import Config, ExtractionEngineConfig
from scribe.db import init_db
from scribe.stages.ingest import ingest_file
from scribe.stages.export import finalize_document
from scribe.stages.redcap import (
    RedcapConfigError,
    RedcapImportError,
    build_redcap_rows,
    export_redcap,
)
from scribe.schema import load_schema
from tests.test_export import add_extraction

SCHEMA = load_schema("schemas/amr_flow_v1.yaml")
API = "https://redcap.example.org/api/"


@pytest.fixture()
def finalized_db(tmp_path):
    cfg = Config(extraction_engine=ExtractionEngineConfig(model="fake"))
    cfg.paths.work = tmp_path / "work"
    cfg.paths.db = tmp_path / "db.sqlite"
    cfg.ingest.denoise = False
    cfg.redcap.api_url = API
    cfg.security.allow_hosts = ["127.0.0.1", "localhost", "redcap.example.org"]
    conn = init_db(cfg.paths.db)
    img = tmp_path / "page.png"
    Image.new("RGB", (400, 300), (246, 246, 244)).save(img)
    doc_id = ingest_file(conn, cfg, img, schema_id="amr_flow_v1")
    page_id = conn.execute("SELECT page_id FROM pages").fetchone()[0]
    add_extraction(conn, page_id, "patient_name", "Ngozi Abara")
    add_extraction(conn, page_id, "patient_age_years", 34)
    add_extraction(conn, page_id, "document_date", None)
    add_extraction(conn, page_id, "medications",
                   [{"drug_name": "Tab X", "dose": "500mg",
                     "frequency": "bd", "duration": None}])
    finalize_document(conn, doc_id, SCHEMA)
    return conn, cfg


def mock_transport(count_holder, status=200, body=None):
    def handler(request: httpx.Request) -> httpx.Response:
        count_holder.append(request)
        if body is not None:
            return httpx.Response(status, text=body)
        data = urllib.parse.parse_qs(request.content.decode())
        n = len(json.loads(data["data"][0]))
        return httpx.Response(status, json={"count": n})
    return httpx.MockTransport(handler)


class TestRowBuilding:
    def test_rows_flatten_correctly(self, finalized_db):
        conn, cfg = finalized_db
        rows = build_redcap_rows(conn, cfg)
        assert len(rows) == 1
        r = rows[0]
        assert r["patient_name"] == "Ngozi Abara"
        assert r["patient_age_years"] == "34"       # strings on the wire
        assert r["document_date"] == ""             # null -> empty
        assert json.loads(r["medications"])[0]["drug_name"] == "Tab X"
        assert "record_id" in r

    def test_field_map_renames(self, finalized_db):
        conn, cfg = finalized_db
        cfg.redcap.field_map = {"patient_name": "pt_name"}
        r = build_redcap_rows(conn, cfg)[0]
        assert r["pt_name"] == "Ngozi Abara"
        assert "patient_name" not in r

    def test_skip_unmapped(self, finalized_db):
        conn, cfg = finalized_db
        cfg.redcap.field_map = {"patient_name": "pt_name"}
        cfg.redcap.skip_unmapped = True
        r = build_redcap_rows(conn, cfg)[0]
        assert set(r) == {"record_id", "pt_name"}


class TestExport:
    def test_happy_path_marks_exported(self, finalized_db, monkeypatch):
        conn, cfg = finalized_db
        monkeypatch.setenv("REDCAP_API_TOKEN", "SECRET123")
        reqs = []
        res = export_redcap(conn, cfg, transport=mock_transport(reqs))
        assert res.imported == 1
        # token travelled in the form body, records marked
        body = urllib.parse.parse_qs(reqs[0].content.decode())
        assert body["token"] == ["SECRET123"]
        assert body["content"] == ["record"]
        row = conn.execute(
            "SELECT exported_at, export_target FROM records").fetchone()
        assert row["exported_at"] and row["export_target"] == API

    def test_host_must_be_allowlisted(self, finalized_db, monkeypatch):
        conn, cfg = finalized_db
        monkeypatch.setenv("REDCAP_API_TOKEN", "T")
        cfg.security.allow_hosts = ["127.0.0.1"]
        with pytest.raises(RedcapConfigError, match="allow_hosts"):
            export_redcap(conn, cfg, transport=mock_transport([]))

    def test_missing_token_fails_without_leaking(self, finalized_db,
                                                 monkeypatch):
        conn, cfg = finalized_db
        monkeypatch.delenv("REDCAP_API_TOKEN", raising=False)
        with pytest.raises(RedcapConfigError, match="REDCAP_API_TOKEN"):
            export_redcap(conn, cfg, transport=mock_transport([]))

    def test_http_error_does_not_mark_exported(self, finalized_db,
                                               monkeypatch):
        conn, cfg = finalized_db
        monkeypatch.setenv("REDCAP_API_TOKEN", "SECRET123")
        tr = mock_transport([], status=403, body='{"error": "bad token"}')
        with pytest.raises(RedcapImportError) as ei:
            export_redcap(conn, cfg, transport=tr)
        assert "SECRET123" not in str(ei.value)     # token never leaks
        assert conn.execute(
            "SELECT exported_at FROM records").fetchone()[0] is None

    def test_count_mismatch_refuses_to_mark(self, finalized_db, monkeypatch):
        conn, cfg = finalized_db
        monkeypatch.setenv("REDCAP_API_TOKEN", "T")
        tr = mock_transport([], body='{"count": 0}')
        with pytest.raises(RedcapImportError, match="accepted 0 of 1"):
            export_redcap(conn, cfg, transport=tr)
        assert conn.execute(
            "SELECT exported_at FROM records").fetchone()[0] is None

    def test_no_api_url_configured(self, finalized_db, monkeypatch):
        conn, cfg = finalized_db
        cfg.redcap.api_url = None
        with pytest.raises(RedcapConfigError, match="api_url"):
            export_redcap(conn, cfg, transport=mock_transport([]))
