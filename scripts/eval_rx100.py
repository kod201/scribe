"""Medicine-level scoring for the rx100 external set.

Two views:
  strict  -- the standard harness comparison (ordered rows, normalized text)
  token   -- per-medicine set matching: a gold medicine counts as found if
             some extracted row shares >= 60% of its word tokens after
             normalization. Separates reading errors from row-order and
             word-order convention differences.

    uv run python scripts/eval_rx100.py --config <config.yaml>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, "src")

from scribe.config import load_config              # noqa: E402
from scribe.db import connect                       # noqa: E402
from scribe.stages.evaluate import (                # noqa: E402
    load_gold,
    pair_id_for_source,
    values_match,
)


def toks(s: str) -> set[str]:
    s = unicodedata.normalize("NFKC", str(s)).lower()
    return set(re.findall(r"[a-z0-9]+", s))


def match(gold_med: str, candidates: list[str]) -> bool:
    g = toks(gold_med)
    if not g:
        return False
    return any(len(g & toks(c)) / len(g) >= 0.6 for c in candidates)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--gold", default="samples/rx100/gold.csv")
    args = ap.parse_args()

    cfg = load_config(args.config)
    conn = connect(cfg.paths.db)
    gold = load_gold(Path(args.gold))

    by_pair = {}
    for r in conn.execute("SELECT doc_id, source_path FROM documents"):
        pid = pair_id_for_source(r["source_path"])
        if pid:
            by_pair[pid] = r["doc_id"]

    n_pages = strict_ok = flagged = 0
    tp = fn = fp = 0
    missing = []
    for pid, fields in sorted(gold.items()):
        doc_id = by_pair.get(pid)
        row = None
        if doc_id:
            row = conn.execute(
                "SELECT e.value, e.flagged FROM extractions e"
                " JOIN pages p USING (page_id) WHERE p.doc_id=?"
                " AND e.field_name='medicines' ORDER BY e.created_at DESC",
                (doc_id,),
            ).fetchone()
        if row is None:
            missing.append(pid)
            continue
        n_pages += 1
        got = json.loads(row["value"]) if row["value"] else None
        gold_rows = fields["medicines"]
        flagged += bool(row["flagged"])
        strict_ok += values_match(got, gold_rows)

        got_names = [r0.get("medicine") or "" for r0 in (got or [])]
        gold_names = [r0["medicine"] for r0 in gold_rows]
        for gm in gold_names:
            if match(gm, got_names):
                tp += 1
            else:
                fn += 1
        for cm in got_names:
            # symmetric direction: a candidate is spurious only if NO gold
            # medicine's tokens are covered by it (gold-denominated, same as
            # the recall direction; schedule tokens like '1-0-1' then cannot
            # penalize a correct row)
            if not any(match(gm, [cm]) for gm in gold_names):
                fp += 1

    # brand-level: is the gold brand token (first word) read anywhere?
    brand_tp = brand_n = 0
    for pid, fields in sorted(gold.items()):
        doc_id = by_pair.get(pid)
        if doc_id is None:
            continue
        row = conn.execute(
            "SELECT e.value FROM extractions e JOIN pages p USING (page_id)"
            " WHERE p.doc_id=? AND e.field_name='medicines'"
            " ORDER BY e.created_at DESC", (doc_id,)).fetchone()
        if row is None:
            continue
        got = json.loads(row["value"]) if row["value"] else None
        all_toks = set()
        for r0 in (got or []):
            all_toks |= toks(r0.get("medicine") or "")
        for r0 in fields["medicines"]:
            brand = next(iter(re.findall(r"[A-Za-z]+", r0["medicine"])), None)
            if brand:
                brand_n += 1
                brand_tp += brand.lower() in all_toks

    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    print(f"config: {args.config}   pages scored: {n_pages}"
          + (f"   MISSING: {len(missing)}" if missing else ""))
    print(f"strict page-level exact : {strict_ok}/{n_pages}"
          f" ({strict_ok / n_pages:.0%})" if n_pages else "no pages")
    print(f"page flag rate          : {flagged / n_pages:.0%}" if n_pages else "")
    print(f"medicine token-match    : precision {prec:.0%}"
          f"  recall {rec:.0%}  F1 {f1:.2f}"
          f"   (tp={tp} fp={fp} fn={fn})")
    print(f"brand-name recall       : {brand_tp}/{brand_n}"
          f" ({brand_tp / brand_n:.0%})" if brand_n else "")


if __name__ == "__main__":
    main()
