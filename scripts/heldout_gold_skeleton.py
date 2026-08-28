"""Two-pass gold.csv skeleton generator for the held-out set.

Pass 1 (default): list images/ -> types.csv (pair_id, document_type to fill).
Pass 2 (--from-types): types.csv -> gold.csv skeleton with one row per
applicable schema field and an example JSON shape for table fields.

    uv run python scripts/heldout_gold_skeleton.py
    uv run python scripts/heldout_gold_skeleton.py --from-types
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "src")

from scribe.schema import load_schema     # noqa: E402

HELDOUT = Path("samples/heldout")
IMAGES = HELDOUT / "images"
TYPES = HELDOUT / "types.csv"
GOLD = HELDOUT / "gold.csv"
SCHEMA = load_schema("schemas/amr_flow_v1.yaml")


def pass1() -> None:
    imgs = sorted(
        p for p in IMAGES.glob("*")
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".heic", ".tiff")
    )
    if not imgs:
        raise SystemExit(f"no images in {IMAGES}/ -- photograph pages first")
    valid = ", ".join(SCHEMA.page_type_ids)
    with TYPES.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["pair_id", "image", f"document_type ({valid})"])
        for p in imgs:
            m = re.match(r"^([A-Z]+_\d+)", p.stem)
            pid = m.group(1) if m else p.stem
            w.writerow([pid, p.name, ""])
    print(f"wrote {TYPES} for {len(imgs)} images.")
    print("Fill the document_type column, then rerun with --from-types.")


def _example(fd) -> str:
    if fd.type != "table":
        return ""
    row = {c.name: None for c in fd.columns or []}
    return "e.g. " + json.dumps([row])


def pass2() -> None:
    if not TYPES.exists():
        raise SystemExit(f"{TYPES} missing -- run pass 1 first")
    rows_out = []
    for r in csv.reader(TYPES.read_text().splitlines()[1:]):
        pid, _img, ptype = r[0], r[1], r[2].strip()
        if ptype not in SCHEMA.page_type_ids:
            raise SystemExit(
                f"{pid}: document_type {ptype!r} is not one of "
                f"{SCHEMA.page_type_ids} -- fix {TYPES}"
            )
        for fd in SCHEMA.fields_for(ptype):
            preset = json.dumps(ptype) if fd.name == "document_type" else ""
            rows_out.append(
                {"pair_id": pid, "page_no": 1, "field_name": fd.name,
                 "gold_json": preset, "hint": _example(fd)}
            )
    if GOLD.exists():
        raise SystemExit(f"{GOLD} already exists -- refusing to overwrite")
    with GOLD.open("w", newline="") as fh:
        w = csv.DictWriter(
            fh, fieldnames=["pair_id", "page_no", "field_name", "gold_json",
                            "hint"])
        w.writeheader()
        w.writerows(rows_out)
    print(f"wrote {GOLD}: {len(rows_out)} field rows to fill.")
    print("Delete the hint column when done (or leave it; eval ignores it).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-types", action="store_true")
    args = ap.parse_args()
    IMAGES.mkdir(parents=True, exist_ok=True)
    pass2() if args.from_types else pass1()
