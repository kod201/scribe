"""Ingest stage tests (M1): dedupe, PDF splitting, deskew, purge, rollback."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from scribe.config import Config, ExtractionEngineConfig
from scribe.db import init_db
from scribe.stages.ingest import (
    estimate_skew_deg,
    file_sha256,
    ingest_file,
    ingest_path,
    purge_document,
)


@pytest.fixture()
def cfg(tmp_path: Path) -> Config:
    c = Config(
        extraction_engine=ExtractionEngineConfig(model="test-model"),
    )
    c.paths.work = tmp_path / "work"
    c.paths.db = tmp_path / "scribe.sqlite"
    c.paths.inbox = tmp_path / "inbox"
    c.paths.exports = tmp_path / "exports"
    c.ingest.denoise = False       # slow and irrelevant to these assertions
    c.ingest.max_edge_px = 1600
    return c


@pytest.fixture()
def conn(cfg: Config):
    return init_db(cfg.paths.db)


def _page_image(text: str = "SAMPLE PAGE", size=(1000, 700)) -> Image.Image:
    im = Image.new("RGB", size, (246, 246, 244))
    d = ImageDraw.Draw(im)
    for i in range(8):
        y = 120 + i * 60
        d.line((80, y, size[0] - 80, y), fill=(140, 140, 140), width=2)
        d.text((90, y - 40), f"{text} line {i}", fill=(30, 30, 60))
    return im


def _save(im: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


# -- happy path --------------------------------------------------------------


def test_single_image_becomes_one_document_one_page(cfg, conn, tmp_path):
    src = _save(_page_image(), tmp_path / "in" / "a.png")
    doc_id = ingest_file(conn, cfg, src)
    assert doc_id == file_sha256(src)[:12]

    doc = conn.execute("SELECT * FROM documents").fetchone()
    assert doc["doc_id"] == doc_id
    assert doc["page_count"] == 1
    assert doc["status"] == "ingested"

    page = conn.execute("SELECT * FROM pages").fetchone()
    assert page["page_no"] == 1
    out = Path(page["image_path"])
    assert out.exists() and out.suffix == ".png"
    assert page["width_px"] == 1000 and page["height_px"] == 700


def test_multipage_pdf_splits_into_pages(cfg, conn, tmp_path):
    pdf = tmp_path / "in" / "doc.pdf"
    pdf.parent.mkdir(parents=True)
    pages = [_page_image(f"PDF PAGE {i}") for i in range(3)]
    pages[0].save(pdf, save_all=True, append_images=pages[1:])

    doc_id = ingest_file(conn, cfg, pdf)
    rows = conn.execute(
        "SELECT page_no, image_path FROM pages WHERE doc_id=? ORDER BY page_no",
        (doc_id,),
    ).fetchall()
    assert [r["page_no"] for r in rows] == [1, 2, 3]
    assert all(Path(r["image_path"]).exists() for r in rows)
    assert conn.execute("SELECT page_count FROM documents").fetchone()[0] == 3


def test_long_edge_is_capped(cfg, conn, tmp_path):
    src = _save(_page_image(size=(4000, 2800)), tmp_path / "in" / "big.png")
    ingest_file(conn, cfg, src)
    page = conn.execute("SELECT width_px, height_px FROM pages").fetchone()
    assert max(page["width_px"], page["height_px"]) == cfg.ingest.max_edge_px


# -- dedupe -------------------------------------------------------------------


def test_same_file_is_never_ingested_twice(cfg, conn, tmp_path):
    src = _save(_page_image(), tmp_path / "in" / "a.png")
    assert ingest_file(conn, cfg, src) is not None
    assert ingest_file(conn, cfg, src) is None
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1


def test_identical_content_different_name_is_a_duplicate(cfg, conn, tmp_path):
    im = _page_image()
    a = _save(im, tmp_path / "in" / "a.png")
    b = tmp_path / "in" / "copy_of_a.png"
    b.write_bytes(a.read_bytes())
    ingest_file(conn, cfg, a)
    assert ingest_file(conn, cfg, b) is None


# -- folder ingest ------------------------------------------------------------


def test_folder_ingest_reports_each_outcome(cfg, conn, tmp_path):
    d = tmp_path / "in"
    _save(_page_image("ONE"), d / "one.png")
    _save(_page_image("TWO"), d / "two.jpg")
    (d / "notes.txt").write_text("not an image")
    bad = d / "broken.png"
    bad.write_bytes(b"this is not a png")

    res = ingest_path(conn, cfg, d)
    assert len(res.ingested) == 2
    assert len(res.failed) == 1 and "broken.png" in res.failed[0][0]
    # .txt is silently not matched by the directory scan
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2


def test_failed_file_leaves_no_partial_rows(cfg, conn, tmp_path):
    bad = tmp_path / "in" / "broken.png"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"junk")
    res = ingest_path(conn, cfg, bad.parent)
    assert res.failed
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0


# -- deskew -------------------------------------------------------------------


def test_skew_estimate_recovers_a_known_rotation():
    img = np.asarray(_page_image("SKEW TEST", size=(1400, 1000)))
    import cv2

    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), -2.5, 1.0)  # tilt 2.5 deg
    tilted = cv2.warpAffine(img, m, (w, h), borderValue=(246, 246, 244))
    est = estimate_skew_deg(tilted)
    assert est == pytest.approx(2.5, abs=0.6)


def test_skew_estimate_returns_zero_without_signal():
    noise = np.random.default_rng(0).integers(
        0, 255, (400, 400, 3), dtype=np.uint8
    )
    assert estimate_skew_deg(noise) == 0.0


def test_upright_page_is_not_rotated(cfg, conn, tmp_path):
    src = _save(_page_image(), tmp_path / "in" / "a.png")
    ingest_file(conn, cfg, src)
    assert conn.execute("SELECT deskew_angle FROM pages").fetchone()[0] == 0.0


# -- purge --------------------------------------------------------------------


def test_purge_removes_rows_and_work_dir(cfg, conn, tmp_path):
    src = _save(_page_image(), tmp_path / "in" / "a.png")
    doc_id = ingest_file(conn, cfg, src)
    work_dir = Path(cfg.paths.work) / doc_id
    assert work_dir.exists()

    assert purge_document(conn, cfg, doc_id) is True
    assert not work_dir.exists()
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0


def test_purge_unknown_doc_returns_false(cfg, conn):
    assert purge_document(conn, cfg, "nope") is False
