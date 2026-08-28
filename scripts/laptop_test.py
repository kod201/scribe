"""The laptop test (PRD 10.1): verify every 'test passes' criterion and print
a pass/fail table. Run after: serve, ingest, run, review (all flags resolved),
finalize, export, eval.

    uv run python scripts/laptop_test.py [--csv <exported.csv>]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

from scribe.config import load_config          # noqa: E402
from scribe.db import connect                   # noqa: E402
from scribe.schema import find_schema           # noqa: E402

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    CHECKS.append((name, ok, detail))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=None,
                    help="Exported CSV to cross-check against records")
    args = ap.parse_args()

    cfg = load_config()
    conn = connect(cfg.paths.db)

    # -- 1. every page produces an extractions row for every schema field ----
    missing: list[str] = []
    pages = conn.execute(
        "SELECT p.page_id, p.page_type, d.doc_id, d.schema_id FROM pages p"
        " JOIN documents d USING (doc_id)").fetchall()
    for pg in pages:
        schema = find_schema(pg["schema_id"])
        expected = {f.name for f in schema.fields_for(pg["page_type"])}
        have = {r[0] for r in conn.execute(
            "SELECT field_name FROM extractions WHERE page_id=?",
            (pg["page_id"],))}
        for f in sorted(expected - have):
            missing.append(f"{pg['doc_id']}.{f}")
    check(
        "every page has an extraction row for every applicable field",
        not missing,
        f"{len(pages)} pages checked" if not missing
        else f"missing: {', '.join(missing[:8])}",
    )

    # -- 2. flag semantics hold (PRD 7.3): required-null, validation-fail,
    #       illegible, and below-threshold fields are all flagged ------------
    bad_flags: list[str] = []
    for pg in pages:
        schema = find_schema(pg["schema_id"])
        for r in conn.execute(
            "SELECT * FROM extractions WHERE page_id=?", (pg["page_id"],)
        ):
            try:
                fd = schema.field(r["field_name"])
            except KeyError:
                continue
            value = json.loads(r["value"]) if r["value"] is not None else None
            thr = fd.threshold(cfg.review_threshold_default)
            must_flag = (
                (fd.required and value is None)
                or r["validation_status"] in ("fail", "unparsed")
                or (r["legible"] is not None and not r["legible"])
                or (value is not None
                    and (r["composite_confidence"] or 0) < thr)
            )
            if must_flag and not r["flagged"]:
                bad_flags.append(f"{pg['doc_id']}.{r['field_name']}")
    check(
        "every null-required / failed / illegible / low-confidence field is flagged",
        not bad_flags,
        "flag rules verified independently of the extractor"
        if not bad_flags else f"unflagged: {', '.join(bad_flags[:8])}",
    )

    # -- 3. nothing flagged reached a record unreviewed ----------------------
    orphans = conn.execute(
        "SELECT COUNT(*) FROM records rec JOIN pages p ON p.doc_id = rec.doc_id"
        " JOIN extractions e ON e.page_id = p.page_id"
        " WHERE e.flagged = 1 AND NOT EXISTS"
        " (SELECT 1 FROM reviews rv WHERE rv.extraction_id = e.extraction_id)"
    ).fetchone()[0]
    n_records = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    check(
        "no flagged field reached a finalized record unreviewed",
        orphans == 0 and n_records > 0,
        f"{n_records} records, {orphans} unreviewed flags inside them",
    )

    # -- 4. provenance: every final value traces to exactly one extraction ---
    prov_bad: list[str] = []
    for rec in conn.execute("SELECT * FROM records"):
        final = json.loads(rec["final_json"])
        prov = json.loads(rec["provenance"])
        if set(final) != set(prov):
            prov_bad.append(rec["record_id"])
            continue
        for fname, link in prov.items():
            row = conn.execute(
                "SELECT flagged FROM extractions WHERE extraction_id=?",
                (link["extraction_id"],)).fetchone()
            if row is None:
                prov_bad.append(f"{rec['record_id']}.{fname}: dangling")
            elif row["flagged"] and not link["review_id"]:
                prov_bad.append(f"{rec['record_id']}.{fname}: flagged, no review")
    check(
        "provenance rule: value -> exactly one extraction (+ review if flagged)",
        not prov_bad,
        "all records traced" if not prov_bad else "; ".join(prov_bad[:5]),
    )

    # -- 5. exported CSV matches the reviewed records -------------------------
    if args.csv and args.csv.exists():
        # newline='' so multi-line quoted cells (free-text fields) survive
        with args.csv.open(newline="") as fh:
            rows = list(csv.DictReader(fh))
        mismatches: list[str] = []
        for row in rows:
            rec = conn.execute(
                "SELECT final_json FROM records WHERE record_id=?",
                (row["record_id"],)).fetchone()
            if rec is None:
                mismatches.append(f"{row['record_id']}: not in records")
                continue
            final = json.loads(rec["final_json"])
            for fname, fval in final.items():
                cell = row.get(fname, "")
                want = (
                    "" if fval is None
                    else json.dumps(fval, ensure_ascii=False)
                    if isinstance(fval, (list, dict)) else str(fval)
                )
                if cell != want:
                    mismatches.append(f"{row['record_id']}.{fname}")
        check(
            "exported CSV matches the reviewed records",
            not mismatches and len(rows) == n_records,
            f"{len(rows)} rows cross-checked"
            if not mismatches else "; ".join(mismatches[:5]),
        )
    else:
        check("exported CSV matches the reviewed records", False,
              "pass --csv <exported file> after scribe export")

    # -- report ----------------------------------------------------------------
    width = max(len(n) for n, _o, _d in CHECKS)
    all_ok = True
    for name, ok, detail in CHECKS:
        mark = "PASS" if ok else "FAIL"
        all_ok &= ok
        print(f"[{mark}] {name.ljust(width)}  {detail}")
    print()
    print("LAPTOP TEST " + ("PASSED" if all_ok else "FAILED")
          + "  (see PRD 10.1; UI and eval criteria verified separately)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
