"""Eval harness (PRD 12): score stored extractions against a gold set.

Works on the model's raw extractions, not on reviewed records -- it measures
the model + validator, and the flag decisions, not the human.

Metrics per field and overall (PRD 12.2):
  exact-match accuracy          -- value equals gold
  auto-accepted accuracy        -- accuracy restricted to unflagged fields;
                                   this is the number that must be >= 98%
  flag rate                     -- share of fields routed to review
  false-negative flag rate      -- NOT flagged but wrong: the metric that
                                   matters most
  hallucination rate            -- gold is null but the model produced a value
                                   while claiming legible: true
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from sqlite3 import Connection
from typing import Any


# -- gold ----------------------------------------------------------------------


def load_gold(path: Path) -> dict[str, dict[str, Any]]:
    """gold.csv -> {pair_id: {field_name: gold_value}}"""
    out: dict[str, dict[str, Any]] = {}
    for r in csv.DictReader(Path(path).read_text().splitlines()):
        out.setdefault(r["pair_id"], {})[r["field_name"]] = json.loads(
            r["gold_json"]
        )
    return out


def pair_id_for_source(source_path: str) -> str | None:
    """AMR_004_HTR.png -> AMR_004; SYN_001.png -> SYN_001."""
    stem = Path(source_path).stem
    m = re.match(r"^([A-Z]+_\d+)", stem)
    return m.group(1) if m else None


# -- comparison ------------------------------------------------------------------


def _norm_str(s: str) -> str:
    """Comparison-only normalisation: case, whitespace runs, unicode punctuation
    lookalikes. The stored value keeps its exact form."""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("’", "'").replace("‘", "'")
    s = s.replace("–", "-").replace("—", "-").replace("×", "x")
    # Separator glyphs are not content: 'E. J', 'E.J' and 'E J' are the same
    # reading, and a trailing period is not a transcription error. Applies to
    # comparison only; stored values keep their exact form.
    s = re.sub(r"[.,;:\-'\u2019]", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def values_match(got: Any, gold: Any) -> bool:
    if got is None or gold is None:
        return got is None and gold is None
    if isinstance(got, bool) != isinstance(gold, bool):
        return False   # True == 1 in Python; not in a clinical record
    if isinstance(gold, str) and isinstance(got, str):
        return _norm_str(got) == _norm_str(gold)
    if isinstance(gold, (int, float)) and isinstance(got, (int, float)) \
            and not isinstance(gold, bool) and not isinstance(got, bool):
        return abs(float(got) - float(gold)) < 1e-9
    if isinstance(gold, list) and isinstance(got, list):
        return len(got) == len(gold) and all(
            values_match(a, b) for a, b in zip(got, gold)
        )
    if isinstance(gold, dict) and isinstance(got, dict):
        return set(got) == set(gold) and all(
            values_match(got[k], gold[k]) for k in gold
        )
    return got == gold


# -- scoring ---------------------------------------------------------------------


@dataclass
class FieldScore:
    n: int = 0
    correct: int = 0
    flagged: int = 0
    auto_accepted: int = 0            # not flagged
    auto_accepted_correct: int = 0
    false_negative_flags: int = 0     # not flagged AND wrong
    halluc_opportunities: int = 0     # gold is null
    hallucinations: int = 0           # gold null, value not null, legible true
    hallucinations_escaped: int = 0   # ...and NOT flagged: the invention
                                      # reaches the record with no human look

    def merged_with(self, other: "FieldScore") -> "FieldScore":
        out = FieldScore()
        for k in vars(out):
            setattr(out, k, getattr(self, k) + getattr(other, k))
        return out


@dataclass
class EvalReport:
    set_name: str
    per_field: dict[str, FieldScore] = field(default_factory=dict)
    missing_pages: list[str] = field(default_factory=list)     # gold, no extraction
    missing_fields: list[str] = field(default_factory=list)    # page.field absent

    @property
    def overall(self) -> FieldScore:
        total = FieldScore()
        for s in self.per_field.values():
            total = total.merged_with(s)
        return total


def evaluate(
    conn: Connection, gold_path: Path, set_name: str = "flow"
) -> EvalReport:
    gold = load_gold(gold_path)
    report = EvalReport(set_name=set_name)

    # source basename -> (page_id, extraction rows)
    docs = {
        r["doc_id"]: r["source_path"]
        for r in conn.execute("SELECT doc_id, source_path FROM documents")
    }
    by_pair: dict[str, str] = {}
    for doc_id, src in docs.items():
        pid = pair_id_for_source(src)
        if pid:
            by_pair[pid] = doc_id

    for pair_id, fields in sorted(gold.items()):
        doc_id = by_pair.get(pair_id)
        if doc_id is None:
            report.missing_pages.append(pair_id)
            continue
        # Newest row per field: a DB holding both whole-page and crop runs
        # must never double count -- the most recent run is the one scored.
        rows = {}
        for r in conn.execute(
            "SELECT e.* FROM extractions e JOIN pages p USING (page_id)"
            " WHERE p.doc_id = ? ORDER BY e.created_at",
            (doc_id,),
        ):
            rows[r["field_name"]] = r
        for fname, gold_value in fields.items():
            row = rows.get(fname)
            if row is None:
                report.missing_fields.append(f"{pair_id}.{fname}")
                continue
            got = json.loads(row["value"]) if row["value"] is not None else None
            flagged = bool(row["flagged"])
            legible = bool(row["legible"]) if row["legible"] is not None else False
            ok = values_match(got, gold_value)

            s = report.per_field.setdefault(fname, FieldScore())
            s.n += 1
            s.correct += ok
            s.flagged += flagged
            if not flagged:
                s.auto_accepted += 1
                s.auto_accepted_correct += ok
                s.false_negative_flags += not ok
            if gold_value is None:
                s.halluc_opportunities += 1
                if got is not None and legible:
                    s.hallucinations += 1
                    if not flagged:
                        s.hallucinations_escaped += 1
    return report


# -- rendering ---------------------------------------------------------------------


def _pct(num: int, den: int) -> str:
    return f"{num / den:.0%}" if den else "-"


def render_markdown(report: EvalReport) -> str:
    lines = [
        f"# Eval report -- **{report.set_name} set**",
        "",
    ]
    if report.set_name == "flow":
        lines += [
            "> Flow set proves plumbing. These numbers are NOT a performance",
            "> claim (PRD 12.1); sign-off metrics come from the held-out set.",
            "",
        ]
    lines += [
        "| field | n | exact acc | auto-acc acc | flag rate | FN flag rate | halluc | halluc esc. |",
        "|---|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for fname in sorted(report.per_field):
        s = report.per_field[fname]
        lines.append(
            f"| {fname} | {s.n} | {_pct(s.correct, s.n)}"
            f" | {_pct(s.auto_accepted_correct, s.auto_accepted)}"
            f" | {_pct(s.flagged, s.n)}"
            f" | {_pct(s.false_negative_flags, s.auto_accepted)}"
            f" | {_pct(s.hallucinations, s.halluc_opportunities)}"
            f" | {_pct(s.hallucinations_escaped, s.halluc_opportunities)} |"
        )
    o = report.overall
    lines.append(
        f"| **overall** | {o.n} | {_pct(o.correct, o.n)}"
        f" | {_pct(o.auto_accepted_correct, o.auto_accepted)}"
        f" | {_pct(o.flagged, o.n)}"
        f" | {_pct(o.false_negative_flags, o.auto_accepted)}"
        f" | {_pct(o.hallucinations, o.halluc_opportunities)}"
        f" | {_pct(o.hallucinations_escaped, o.halluc_opportunities)} |"
    )
    if report.missing_pages:
        lines += ["", f"Missing pages (gold but never extracted): "
                      f"{', '.join(report.missing_pages)}"]
    if report.missing_fields:
        lines += ["", f"Missing fields: {len(report.missing_fields)} "
                      f"(first 10: {', '.join(report.missing_fields[:10])})"]
    return "\n".join(lines)
