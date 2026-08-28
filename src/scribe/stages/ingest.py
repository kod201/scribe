"""Stage 1: ingest (PRD 5.1).

Load image/PDF, dedupe by hash, deskew/denoise, normalize size, split
multi-page PDFs. Every accepted source becomes one `documents` row and one
`pages` row per page, with the normalized page image under
`paths.work/<doc_id>/`.

Idempotent: the same file (by sha256) is never ingested twice.
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import Connection
from typing import Iterator

import cv2
import numpy as np
from PIL import Image, ImageOps

from scribe.config import Config

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}
HEIC_SUFFIXES = {".heic", ".heif"}
PDF_SUFFIXES = {".pdf"}
ACCEPTED = IMAGE_SUFFIXES | HEIC_SUFFIXES | PDF_SUFFIXES

# Deskew is only trusted for small scan/photo tilts. Beyond this the estimate
# is more likely a table edge or a rotated photo, which is a human problem.
MAX_DESKEW_DEG = 10.0
MIN_DESKEW_DEG = 0.3


@dataclass
class IngestResult:
    ingested: list[str] = field(default_factory=list)   # doc_ids
    skipped_duplicate: list[str] = field(default_factory=list)   # source paths
    skipped_unsupported: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (path, error)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_source_files(path: Path) -> Iterator[Path]:
    """Yield acceptable files under `path` (or `path` itself), sorted."""
    if path.is_file():
        yield path
        return
    for p in sorted(path.rglob("*")):
        if p.is_file() and p.suffix.lower() in ACCEPTED and not p.name.startswith("."):
            yield p


# -- page rendering ---------------------------------------------------------


def load_image_pages(path: Path) -> list[Image.Image]:
    """A single image file is one page. Multi-frame TIFFs contribute a page
    per frame. EXIF orientation is applied so phone photos come in upright."""
    im = Image.open(path)
    pages: list[Image.Image] = []
    n = getattr(im, "n_frames", 1)
    for i in range(n):
        if n > 1:
            im.seek(i)
        pages.append(ImageOps.exif_transpose(im.convert("RGB")))
    return pages


def load_heic_pages(path: Path) -> list[Image.Image]:
    """iPhone HEIC/HEIF photos. Pillow needs a plugin for these; fall back to
    macOS `sips` when pillow-heif is not installed."""
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
        return load_image_pages(path)
    except ImportError:
        pass
    import subprocess
    import tempfile

    sips = shutil.which("sips")
    if sips is None:
        raise ValueError(
            "HEIC file but neither pillow-heif nor macOS sips is available"
        )
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / (path.stem + ".png")
        r = subprocess.run(
            [sips, "-s", "format", "png", str(path), "--out", str(out)],
            capture_output=True, text=True,
        )
        if r.returncode != 0 or not out.exists():
            raise ValueError(f"sips could not convert {path.name}: {r.stderr.strip()}")
        # sips already applies EXIF orientation; load_image_pages re-applying
        # exif_transpose on the PNG is a no-op (the PNG carries no EXIF).
        return load_image_pages(out)


def render_pdf_pages(path: Path, target_dpi: int) -> list[Image.Image]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    try:
        scale = target_dpi / 72.0
        return [
            page.render(scale=scale).to_pil().convert("RGB")
            for page in pdf
        ]
    finally:
        pdf.close()


# -- preprocessing ------------------------------------------------------------


def estimate_skew_deg(img: np.ndarray) -> float:
    """Estimate page tilt from near-horizontal line segments.

    Positive return value means the content is rotated counter-clockwise and
    needs a clockwise correction. Returns 0.0 when there is not enough signal
    to trust an estimate -- a wrong deskew is worse than none.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if img.ndim == 3 else img
    edges = cv2.Canny(gray, 60, 180)
    min_len = max(gray.shape[1] // 8, 80)
    # maxLineGap must tolerate the pixel stepping of an anti-aliased tilted
    # line, which Canny breaks into short collinear runs; 8px was too strict
    # and found nothing on a 0.7-degree tilt.
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 360, threshold=60,
        minLineLength=min_len, maxLineGap=20,
    )
    if lines is None:
        return 0.0
    angles = []
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
        ang = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        # Fold onto (-45, 45] and keep only near-horizontal candidates.
        if ang > 45:
            ang -= 90
        elif ang <= -45:
            ang += 90
        if abs(ang) <= MAX_DESKEW_DEG:
            angles.append(ang)
    if len(angles) < 5:
        return 0.0
    # Real page structure produces many segments that agree; noise produces a
    # scatter. Refuse to deskew unless the candidates cluster.
    q1, q3 = np.percentile(angles, [25, 75])
    if q3 - q1 > 2.0:
        return 0.0
    return float(np.median(angles))


def deskew(img: np.ndarray, angle_deg: float) -> np.ndarray:
    if abs(angle_deg) < MIN_DESKEW_DEG:
        return img
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle_deg, 1.0)
    return cv2.warpAffine(
        img, m, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(246, 246, 244),
    )


def denoise(img: np.ndarray) -> np.ndarray:
    """Conservative on purpose: aggressive denoising eats pen strokes, and a
    slightly noisy page is better than a smoothed-away decimal point."""
    return cv2.fastNlMeansDenoisingColored(img, None, 3, 3, 7, 21)


def cap_long_edge(img: np.ndarray, max_edge_px: int) -> np.ndarray:
    h, w = img.shape[:2]
    edge = max(h, w)
    if edge <= max_edge_px:
        return img
    s = max_edge_px / edge
    return cv2.resize(img, (round(w * s), round(h * s)),
                      interpolation=cv2.INTER_AREA)


def preprocess_page(
    pil_img: Image.Image, cfg: Config
) -> tuple[Image.Image, float]:
    """Full page normalization. Returns (image, applied_deskew_angle)."""
    img = np.asarray(pil_img)
    img = cap_long_edge(img, cfg.ingest.max_edge_px)
    angle = 0.0
    if cfg.ingest.deskew:
        angle = estimate_skew_deg(img)
        img = deskew(img, angle)
        if abs(angle) < MIN_DESKEW_DEG:
            angle = 0.0
    if cfg.ingest.denoise:
        img = denoise(img)
    return Image.fromarray(img), angle


# -- database -----------------------------------------------------------------


def ingest_file(
    conn: Connection, cfg: Config, src: Path, schema_id: str | None = None
) -> str | None:
    """Ingest one file. Returns the new doc_id, or None if it was a duplicate."""
    digest = file_sha256(src)
    dup = conn.execute(
        "SELECT doc_id FROM documents WHERE file_hash = ?", (digest,)
    ).fetchone()
    if dup:
        return None

    if src.suffix.lower() in PDF_SUFFIXES:
        pil_pages = render_pdf_pages(src, cfg.ingest.target_dpi)
    elif src.suffix.lower() in HEIC_SUFFIXES:
        pil_pages = load_heic_pages(src)
    else:
        pil_pages = load_image_pages(src)
    if not pil_pages:
        raise ValueError("no pages could be rendered")

    doc_id = digest[:12]
    doc_dir = Path(cfg.paths.work) / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    try:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO documents"
            " (doc_id, file_hash, source_path, page_count, schema_id,"
            "  ingested_at, status)"
            " VALUES (?,?,?,?,?,?, 'ingested')",
            (doc_id, digest, str(src.resolve()), len(pil_pages), schema_id, now),
        )
        for i, pil in enumerate(pil_pages, start=1):
            page, angle = preprocess_page(pil, cfg)
            out = doc_dir / f"page_{i:04d}.png"
            page.save(out, "PNG")
            conn.execute(
                "INSERT INTO pages"
                " (page_id, doc_id, page_no, image_path, width_px, height_px,"
                "  deskew_angle)"
                " VALUES (?,?,?,?,?,?,?)",
                (uuid.uuid4().hex[:16], doc_id, i, str(out),
                 page.width, page.height, angle),
            )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        shutil.rmtree(doc_dir, ignore_errors=True)
        raise
    return doc_id


def ingest_path(
    conn: Connection, cfg: Config, path: Path, schema_id: str | None = None
) -> IngestResult:
    res = IngestResult()
    if path.is_file() and path.suffix.lower() not in ACCEPTED:
        res.skipped_unsupported.append(str(path))
        return res
    for src in iter_source_files(path):
        try:
            doc_id = ingest_file(conn, cfg, src, schema_id)
        except Exception as e:  # noqa: BLE001 -- one bad file must not stop a batch
            res.failed.append((str(src), str(e)))
            continue
        if doc_id is None:
            res.skipped_duplicate.append(str(src))
        else:
            res.ingested.append(doc_id)
    return res


def purge_document(conn: Connection, cfg: Config, doc_id: str) -> bool:
    """Remove every artifact for a document: DB rows (cascade) and the work
    directory with page images and crops (PRD 13)."""
    row = conn.execute(
        "SELECT doc_id FROM documents WHERE doc_id = ?", (doc_id,)
    ).fetchone()
    if not row:
        return False
    conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    shutil.rmtree(Path(cfg.paths.work) / doc_id, ignore_errors=True)
    return True
