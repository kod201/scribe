"""SQLite provenance and pipeline state (PRD 8).

Provenance rule: a value in `records` must trace to exactly one `extractions`
row (and a `reviews` row if it was flagged). No orphan values.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    doc_id      TEXT PRIMARY KEY,
    file_hash   TEXT NOT NULL UNIQUE,       -- sha256, drives dedupe on ingest
    source_path TEXT NOT NULL,
    page_count  INTEGER NOT NULL DEFAULT 0,
    schema_id   TEXT,
    ingested_at TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ingested'
        CHECK (status IN ('ingested','extracted','in_review','finalized','failed'))
);

CREATE TABLE IF NOT EXISTS pages (
    page_id      TEXT PRIMARY KEY,
    doc_id       TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    page_no      INTEGER NOT NULL,
    image_path   TEXT NOT NULL,
    width_px     INTEGER,
    height_px    INTEGER,
    page_type    TEXT,
    deskew_angle REAL,
    UNIQUE (doc_id, page_no)
);

CREATE TABLE IF NOT EXISTS regions (
    region_id      TEXT PRIMARY KEY,
    page_id        TEXT NOT NULL REFERENCES pages(page_id) ON DELETE CASCADE,
    bbox           TEXT NOT NULL,           -- json [x0,y0,x1,y1] in page px
    region_type    TEXT,
    is_handwritten INTEGER,
    reading_order  INTEGER,
    layout_engine  TEXT NOT NULL,
    engine_version TEXT
);

CREATE TABLE IF NOT EXISTS extractions (
    extraction_id        TEXT PRIMARY KEY,
    page_id              TEXT NOT NULL REFERENCES pages(page_id) ON DELETE CASCADE,
    field_name           TEXT NOT NULL,
    region_id            TEXT REFERENCES regions(region_id) ON DELETE SET NULL,
    crop_path            TEXT,
    value                TEXT,              -- json-encoded coerced value, null allowed
    raw_transcription    TEXT,
    legible              INTEGER,
    note                 TEXT,
    model_confidence     REAL,
    composite_confidence REAL,
    validation_status    TEXT NOT NULL DEFAULT 'pending'
        CHECK (validation_status IN ('pending','pass','fail','unparsed')),
    validation_errors    TEXT,              -- json list of messages
    flagged              INTEGER NOT NULL DEFAULT 0,
    flag_reason          TEXT,
    model_name           TEXT NOT NULL,
    model_version        TEXT,
    prompt_version       TEXT NOT NULL,
    latency_ms           INTEGER,
    created_at           TEXT NOT NULL,
    UNIQUE (page_id, field_name, prompt_version)
);

CREATE TABLE IF NOT EXISTS reviews (
    review_id       TEXT PRIMARY KEY,
    extraction_id   TEXT NOT NULL REFERENCES extractions(extraction_id) ON DELETE CASCADE,
    reviewer        TEXT NOT NULL,
    action          TEXT NOT NULL CHECK (action IN ('accept','correct','reject')),
    corrected_value TEXT,                   -- json-encoded; null for accept/reject
    comment         TEXT,
    reviewed_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS records (
    record_id     TEXT PRIMARY KEY,
    doc_id        TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    schema_id     TEXT NOT NULL,
    final_json    TEXT NOT NULL,
    provenance    TEXT NOT NULL,            -- field -> {extraction_id, review_id}
    finalized_at  TEXT NOT NULL,
    exported_at   TEXT,
    export_target TEXT
);

CREATE INDEX IF NOT EXISTS idx_pages_doc          ON pages(doc_id);
CREATE INDEX IF NOT EXISTS idx_regions_page       ON regions(page_id);
CREATE INDEX IF NOT EXISTS idx_extractions_page   ON extractions(page_id);
CREATE INDEX IF NOT EXISTS idx_extractions_flag   ON extractions(flagged);
CREATE INDEX IF NOT EXISTS idx_extractions_field  ON extractions(field_name);
CREATE INDEX IF NOT EXISTS idx_reviews_extraction ON reviews(extraction_id);
CREATE INDEX IF NOT EXISTS idx_records_doc        ON records(doc_id);

-- The review queue: flagged extractions with no review yet. The UI reads this
-- rather than recomputing the flag logic (PRD 9).
CREATE VIEW IF NOT EXISTS review_queue AS
SELECT e.extraction_id, e.page_id, p.doc_id, p.page_no, e.field_name,
       e.value, e.raw_transcription, e.legible, e.note, e.crop_path,
       e.composite_confidence, e.flag_reason, e.validation_errors
FROM   extractions e
JOIN   pages p ON p.page_id = e.page_id
WHERE  e.flagged = 1
  AND  NOT EXISTS (SELECT 1 FROM reviews r WHERE r.extraction_id = e.extraction_id);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open the database, creating it and its schema if absent."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False lets the review UI's threadpool share the
    # connection; CPython's sqlite3 is built serialized (threadsafety 3), so
    # the module itself locks around every statement.
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path: Path | str) -> sqlite3.Connection:
    conn = connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    return conn


def counts(conn: sqlite3.Connection) -> dict[str, Any]:
    """Row counts per table, for `scribe status`."""
    out: dict[str, Any] = {}
    for t in ("documents", "pages", "regions", "extractions", "reviews", "records"):
        out[t] = conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
    out["review_queue"] = conn.execute(
        "SELECT COUNT(*) AS n FROM review_queue"
    ).fetchone()["n"]
    return out
