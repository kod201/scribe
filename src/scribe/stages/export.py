"""Stage 6: finalize + export (PRD 5.1, 8, 9).

Finalization builds the `records` row for a document. It refuses while any
flagged extraction lacks a review -- nothing low-confidence reaches the sink
unreviewed. Provenance maps every field to exactly one extraction (and the
review that resolved it, when there was one).

Export renders finalized records to CSV or JSONL. The REDCap adapter is a
stub by design (PRD 3).
"""

from __future__ import annotations

import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from scribe.schema import Schema


class UnresolvedFlagsError(RuntimeError):
    def __init__(self, doc_id: str, fields: list[str]):
        self.fields = fields
        super().__init__(
            f"document {doc_id} still has unresolved flags on: "
            + ", ".join(fields)
        )


def unresolved_flags(conn: Connection, doc_id: str) -> list[str]:
    return [
        r["field_name"]
        for r in conn.execute(
            "SELECT field_name FROM review_queue WHERE doc_id = ?", (doc_id,)
        )
    ]


def finalize_document(
    conn: Connection, doc_id: str, schema: Schema
) -> str:
    """Build the final record for a document. Returns the record_id.

    Corrections update the record, never the extraction (PRD 9): the
    extraction row keeps what the model said; the review row keeps what the
    human decided; the record carries the resolved value.
    """
    pending = unresolved_flags(conn, doc_id)
    if pending:
        raise UnresolvedFlagsError(doc_id, pending)

    rows = conn.execute(
        "SELECT e.*, p.page_no FROM extractions e JOIN pages p USING (page_id)"
        " WHERE p.doc_id = ? ORDER BY p.page_no",
        (doc_id,),
    ).fetchall()
    if not rows:
        raise ValueError(f"document {doc_id} has no extractions to finalize")

    final: dict[str, Any] = {}
    provenance: dict[str, dict[str, str | None]] = {}
    for row in rows:
        review = conn.execute(
            "SELECT * FROM reviews WHERE extraction_id = ?"
            " ORDER BY reviewed_at DESC LIMIT 1",
            (row["extraction_id"],),
        ).fetchone()

        value = json.loads(row["value"]) if row["value"] is not None else None
        review_id = None
        if review:
            review_id = review["review_id"]
            if review["action"] == "correct":
                value = (
                    json.loads(review["corrected_value"])
                    if review["corrected_value"] is not None else None
                )
            elif review["action"] == "reject":
                value = None

        final[row["field_name"]] = value
        provenance[row["field_name"]] = {
            "extraction_id": row["extraction_id"],
            "review_id": review_id,
        }

    record_id = uuid.uuid4().hex[:16]
    conn.execute(
        "INSERT INTO records (record_id, doc_id, schema_id, final_json,"
        " provenance, finalized_at) VALUES (?,?,?,?,?,?)",
        (
            record_id, doc_id, schema.schema_id,
            json.dumps(final, ensure_ascii=False),
            json.dumps(provenance, ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.execute(
        "UPDATE documents SET status='finalized' WHERE doc_id=?", (doc_id,)
    )
    return record_id


# -- export -----------------------------------------------------------------


def _fetch_records(
    conn: Connection, schema_id: str | None = None
) -> list[Any]:
    q = ("SELECT r.*, d.source_path FROM records r JOIN documents d USING (doc_id)")
    args: tuple[Any, ...] = ()
    if schema_id:
        q += " WHERE r.schema_id = ?"
        args = (schema_id,)
    return conn.execute(q + " ORDER BY r.finalized_at", args).fetchall()


def _mark_exported(conn: Connection, record_ids: list[str], target: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        "UPDATE records SET exported_at=?, export_target=? WHERE record_id=?",
        [(now, target, rid) for rid in record_ids],
    )


def export_jsonl(
    conn: Connection, out_path: Path, schema_id: str | None = None
) -> int:
    rows = _fetch_records(conn, schema_id)
    with out_path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps({
                "record_id": r["record_id"],
                "doc_id": r["doc_id"],
                "schema_id": r["schema_id"],
                "source_path": r["source_path"],
                "finalized_at": r["finalized_at"],
                "fields": json.loads(r["final_json"]),
            }, ensure_ascii=False) + "\n")
    _mark_exported(conn, [r["record_id"] for r in rows], str(out_path))
    return len(rows)


def export_csv(
    conn: Connection, out_path: Path, schema_id: str | None = None
) -> int:
    """One row per record. Scalar fields as text; tables and lists as JSON in
    their cell -- CSV is a flat sink, not a place to invent a normal form."""
    rows = _fetch_records(conn, schema_id)
    field_names: list[str] = []
    dicts = []
    for r in rows:
        fields = json.loads(r["final_json"])
        for k in fields:
            if k not in field_names:
                field_names.append(k)
        dicts.append((r, fields))

    header = ["record_id", "doc_id", "schema_id", "source_path"] + field_names
    with out_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r, fields in dicts:
            row_out = [r["record_id"], r["doc_id"], r["schema_id"],
                       r["source_path"]]
            for k in field_names:
                v = fields.get(k)
                if isinstance(v, (list, dict)):
                    row_out.append(json.dumps(v, ensure_ascii=False))
                elif v is None:
                    row_out.append("")
                else:
                    row_out.append(str(v))
            w.writerow(row_out)
    _mark_exported(conn, [r["record_id"] for r, _f in dicts], str(out_path))
    return len(rows)

