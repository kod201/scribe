"""Crop-based extraction tests (M1b): localization, fallback, provenance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from scribe.config import Config, ExtractionEngineConfig
from scribe.db import init_db
from scribe.engines.base import EngineHealth, LayoutEngine
from scribe.engines.grounding import QwenGroundingLayout, crop_region
from scribe.schema import load_schema
from scribe.stages.extract import effective_prompt_version, extract_page
from scribe.stages.ingest import ingest_file
from tests.test_extract import FakeEngine, env

SCHEMA = load_schema("schemas/amr_flow_v1.yaml")


class FakeLocator(LayoutEngine):
    """Locates a fixed subset of fields; everything else is 'not found'."""

    name = "fake_locator"
    version = "test"

    def __init__(self, boxes: dict[str, tuple[int, int, int, int]]):
        self.boxes = boxes
        self.calls: list[list[str]] = []

    def health(self) -> EngineHealth:
        return EngineHealth(ok=True, backend=self.name, detail="fake")

    def detect(self, image_path):
        return []

    def locate_fields(self, image_path, fields):
        self.calls.append([n for n, _d in fields])
        return {n: self.boxes[n] for n, _d in fields if n in self.boxes}


@pytest.fixture()
def env_page(tmp_path):
    cfg = Config(extraction_engine=ExtractionEngineConfig(model="fake"))
    cfg.paths.work = tmp_path / "work"
    cfg.paths.db = tmp_path / "db.sqlite"
    cfg.ingest.denoise = False
    conn = init_db(cfg.paths.db)
    img = tmp_path / "page.png"
    Image.new("RGB", (1000, 800), (246, 246, 244)).save(img)
    ingest_file(conn, cfg, img)
    return cfg, conn, conn.execute("SELECT * FROM pages").fetchone()


def visit_note_responses(values: dict) -> list[str]:
    out = [env("visit_note", raw="visit_note")]
    for fd in SCHEMA.fields_for("visit_note"):
        if fd.name == "document_type":
            continue
        v = values.get(fd.name)
        out.append(env(v, raw=json.dumps(v)))
    return out


VALS = {"patient_name": "X", "patient_age_years": 28, "patient_sex": "male",
        "hospital_number": "1", "document_date": "23/03/2026",
        "chief_complaint": "c", "assessment": "a", "plan": "p"}


class TestCropMode:
    def test_located_fields_get_crops_and_regions(self, env_page):
        cfg, conn, row = env_page
        layout = FakeLocator({"patient_name": (100, 100, 400, 160),
                              "hospital_number": (100, 200, 400, 260)})
        eng = FakeEngine(visit_note_responses(VALS))
        extract_page(conn, cfg, eng, SCHEMA, row, layout=layout)

        # classification was not localized
        assert "document_type" not in layout.calls[0]
        regions = conn.execute("SELECT * FROM regions").fetchall()
        assert len(regions) == 2
        assert all(r["layout_engine"] == "fake_locator" for r in regions)

        located = conn.execute(
            "SELECT field_name, crop_path, region_id FROM extractions"
            " WHERE crop_path IS NOT NULL").fetchall()
        assert {r["field_name"] for r in located} == {
            "patient_name", "hospital_number"}
        for r in located:
            assert Path(r["crop_path"]).exists()
            assert r["region_id"] is not None

    def test_unlocated_fields_fall_back_to_whole_page(self, env_page):
        cfg, conn, row = env_page
        layout = FakeLocator({"patient_name": (100, 100, 400, 160)})
        eng = FakeEngine(visit_note_responses(VALS))
        extract_page(conn, cfg, eng, SCHEMA, row, layout=layout)

        fallback = conn.execute(
            "SELECT COUNT(*) FROM extractions WHERE crop_path IS NULL"
            " AND field_name != 'document_type'").fetchone()[0]
        assert fallback == len(SCHEMA.fields_for("visit_note")) - 2

    def test_crop_prompt_carries_crop_context(self, env_page):
        cfg, conn, row = env_page
        layout = FakeLocator({"patient_name": (100, 100, 400, 160)})
        eng = FakeEngine(visit_note_responses(VALS))
        extract_page(conn, cfg, eng, SCHEMA, row, layout=layout)
        by_field = {}
        for call in eng.calls[1:]:
            for fd in SCHEMA.fields:
                if f"Field to extract: {fd.name} " in call["user"]:
                    by_field[fd.name] = call["user"]
        assert "cropped region" in by_field["patient_name"]
        assert "cropped region" not in by_field["hospital_number"]

    def test_modes_do_not_collide(self, env_page):
        """Whole-page and crop runs coexist under distinct prompt_versions."""
        cfg, conn, row = env_page
        eng = FakeEngine(visit_note_responses(VALS))
        extract_page(conn, cfg, eng, SCHEMA, row)               # whole page

        layout = FakeLocator({})
        assert effective_prompt_version(layout) != effective_prompt_version(None)
        eng2 = FakeEngine(visit_note_responses(VALS))
        row2 = conn.execute("SELECT * FROM pages").fetchone()
        extract_page(conn, cfg, eng2, SCHEMA, row2, layout=layout)  # crop mode
        assert len(eng2.calls) > 0    # re-extracted, not reused

        versions = {r[0] for r in conn.execute(
            "SELECT DISTINCT prompt_version FROM extractions")}
        assert len(versions) == 2


class TestRouting:
    def test_only_routed_types_are_cropped(self, env_page):
        cfg, conn, row = env_page
        cfg.crop_field_types = ["date"]
        layout = FakeLocator({"patient_name": (100, 100, 400, 160),
                              "document_date": (100, 300, 400, 360)})
        eng = FakeEngine(visit_note_responses(VALS))
        extract_page(conn, cfg, eng, SCHEMA, row, layout=layout)
        # only document_date was even submitted for localization
        assert layout.calls == [["document_date"]]
        cropped = {r[0] for r in conn.execute(
            "SELECT field_name FROM extractions WHERE crop_path IS NOT NULL")}
        assert cropped == {"document_date"}

    def test_routed_version_key_is_distinct(self):
        lay = FakeLocator({})
        assert effective_prompt_version(lay, ["date", "table"]) != \
            effective_prompt_version(lay, None)
        assert effective_prompt_version(lay, ["table", "date"]) == \
            effective_prompt_version(lay, ["date", "table"])   # order-free


class TestVerifyPass:
    def _run(self, env_page, responses, boxes=None):
        cfg, conn, row = env_page
        cfg.verify_pass = True
        cfg.crop_field_types = ["date"]
        layout = FakeLocator(boxes if boxes is not None else {
            "document_date": (100, 300, 400, 360),
            "patient_name": (100, 100, 400, 160),
        })
        eng = FakeEngine(responses)
        extract_page(conn, cfg, eng, SCHEMA, row, layout=layout)
        return conn, eng

    def _responses(self, primary, verify):
        """document_type, then per visit_note field primary(+verify)."""
        out = [env("visit_note", raw="visit_note")]
        for fd in SCHEMA.fields_for("visit_note"):
            if fd.name == "document_type":
                continue
            v = primary.get(fd.name)
            out.append(env(v, raw=json.dumps(v)))
            if v is not None:                      # verify only on non-null
                out.append(env(verify.get(fd.name, v),
                               raw=json.dumps(verify.get(fd.name, v))))
        return out

    def test_agreement_stays_unflagged(self, env_page):
        conn, eng = self._run(
            env_page, self._responses(VALS, VALS))
        row = conn.execute(
            "SELECT flagged FROM extractions WHERE field_name='patient_name'"
        ).fetchone()
        assert row["flagged"] == 0

    def test_disagreement_flags_with_reason(self, env_page):
        verify = dict(VALS, patient_name="Y")     # second read differs
        conn, eng = self._run(env_page, self._responses(VALS, verify))
        row = conn.execute(
            "SELECT flagged, flag_reason, composite_confidence FROM extractions"
            " WHERE field_name='patient_name'").fetchone()
        assert row["flagged"] == 1
        assert "verify pass disagreement" in row["flag_reason"]

    def test_null_values_are_not_verified(self, env_page):
        vals = dict(VALS, assessment=None)
        conn, eng = self._run(env_page, self._responses(vals, vals))
        # every non-null field: 1 primary + 1 verify; assessment: primary only
        asked = sum("Field to extract: assessment " in c["user"]
                    for c in eng.calls)
        assert asked == 1

    def test_verify_version_key_is_distinct(self):
        lay = FakeLocator({})
        assert effective_prompt_version(lay, ["date"], True) != \
            effective_prompt_version(lay, ["date"], False)


class TestCrossModelVerify:
    def test_verify_calls_go_to_the_second_engine(self, env_page):
        cfg, conn, row = env_page
        cfg.verify_pass = True
        cfg.crop_field_types = ["date"]
        layout = FakeLocator({"document_date": (100, 300, 400, 360)})
        primary = FakeEngine([env("visit_note", raw="visit_note")] + [
            env(VALS.get(fd.name), raw=json.dumps(VALS.get(fd.name)))
            for fd in SCHEMA.fields_for("visit_note")
            if fd.name != "document_type"
        ])
        verifier = FakeEngine(default=env("DISAGREE", raw="DISAGREE"))
        extract_page(conn, cfg, primary, SCHEMA, row, layout=layout,
                     verify_engine=verifier)
        # verifier saw every non-null field exactly once; primary never
        # received a verify call (its queue was sized for primaries only)
        n_nonnull = sum(1 for fd in SCHEMA.fields_for("visit_note")
                        if fd.name != "document_type"
                        and VALS.get(fd.name) is not None)
        assert len(verifier.calls) == n_nonnull
        assert primary.responses == []

    def test_second_model_verifies_even_without_a_crop(self, env_page):
        """No crop for a field: same-model verify is pointless (temp 0 ->
        identical), but a different model still gives an independent read."""
        cfg, conn, row = env_page
        cfg.verify_pass = True
        cfg.crop_field_types = ["date"]
        layout = FakeLocator({})            # nothing localized at all
        primary = FakeEngine([env("visit_note", raw="visit_note")] + [
            env(VALS.get(fd.name), raw=json.dumps(VALS.get(fd.name)))
            for fd in SCHEMA.fields_for("visit_note")
            if fd.name != "document_type"
        ])
        verifier = FakeEngine(default=env("Y", raw="Y"))
        extract_page(conn, cfg, primary, SCHEMA, row, layout=layout,
                     verify_engine=verifier)
        assert len(verifier.calls) > 0
        flagged = conn.execute(
            "SELECT COUNT(*) FROM extractions WHERE flag_reason LIKE"
            " '%verify pass disagreement%'").fetchone()[0]
        assert flagged > 0

    def test_version_key_carries_verifier_model(self):
        lay = FakeLocator({})
        a = effective_prompt_version(lay, ["date"], True, None)
        b = effective_prompt_version(lay, ["date"], True,
                                     "mlx-community/Qwen3-VL-8B-Instruct-8bit")
        assert a != b and "Qwen3-VL-8B" in b


class TestGroundingParsing:
    def test_normalized_coords_scale_to_pixels(self, tmp_path):
        img = tmp_path / "p.png"
        Image.new("RGB", (2000, 1000), "white").save(img)
        eng = FakeEngine([json.dumps({"regions": [
            {"label": "a", "bbox_2d": [100, 200, 500, 400]},
            {"label": "ignored", "bbox_2d": [0, 0, 10, 10]},
            {"label": "b", "bbox_2d": [1, 2, 3]},           # malformed
            {"label": "c", "bbox_2d": [500, 500, 100, 100]},  # inverted
        ]})])
        lay = QwenGroundingLayout(eng)
        out = lay.locate_fields(img, [("a", "d"), ("b", "d"), ("c", "d")])
        assert out == {"a": (200, 200, 1000, 400)}

    def test_echoed_listing_labels_still_match(self, tmp_path):
        """Muse Glimmer echoes the whole listing line as the label."""
        img = tmp_path / "p.png"
        Image.new("RGB", (1000, 1000), "white").save(img)
        eng = FakeEngine([json.dumps({"regions": [
            {"label": "label 'patient_name': the handwritten value",
             "bbox_2d": [100, 100, 200, 200]},
            {"label": "mentions patient_name and vitals_table",  # ambiguous
             "bbox_2d": [300, 300, 400, 400]},
        ]})])
        lay = QwenGroundingLayout(eng)
        out = lay.locate_fields(img, [("patient_name", "d"),
                                      ("vitals_table", "d")])
        assert set(out) == {"patient_name"}   # ambiguous row dropped

    def test_unparseable_locate_returns_empty(self, tmp_path):
        img = tmp_path / "p.png"
        Image.new("RGB", (100, 100), "white").save(img)
        lay = QwenGroundingLayout(FakeEngine(["not json"]))
        assert lay.locate_fields(img, [("a", "d")]) == {}

    def test_crop_region_clamps_and_pads(self, tmp_path):
        img = tmp_path / "p.png"
        Image.new("RGB", (300, 200), "white").save(img)
        out = crop_region(img, (0, 0, 100, 100), tmp_path / "c.png",
                          margin_px=50)
        with Image.open(out) as c:
            assert c.size == (150, 150)   # clamped at page origin
