"""Pull the AMR flow set from HuggingFace into ./samples/flow (PRD 10.1, 12.1).

Flow set only. It proves plumbing; it never produces a performance claim.
This is a setup step and is the one place network access is expected --
`scribe run` itself is guarded offline.

    uv run python scripts/pull_amr.py --limit 20
"""

from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

from huggingface_hub import hf_hub_download

REPO = "Nigeria-Health-data-OCR-pipeline/African-Medical-Records"
REVISION = "fa27d29dae4128ac45f035fd580928c84bec4e98"  # pinned for reproducibility
OUT = Path("samples/flow")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20,
                    help="Number of pairs to pull (PRD asks for 10-20).")
    ap.add_argument("--single-page-only", action="store_true", default=True,
                    help="Skip multi-page records for the v0 flow set.")
    args = ap.parse_args()

    (OUT / "images").mkdir(parents=True, exist_ok=True)
    (OUT / "truth").mkdir(parents=True, exist_ok=True)

    meta_path = hf_hub_download(REPO, "metadata.csv", repo_type="dataset",
                                revision=REVISION)
    rows = list(csv.DictReader(Path(meta_path).read_text().splitlines()))

    picked, manifest = 0, []
    for row in rows:
        if picked >= args.limit:
            break
        pages = row["htr_file"].split(";")
        if args.single_page_only and len(pages) > 1:
            continue

        img_src = hf_hub_download(REPO, pages[0], repo_type="dataset",
                                  revision=REVISION)
        txt_src = hf_hub_download(REPO, row["truth_file"], repo_type="dataset",
                                  revision=REVISION)
        img_dst = OUT / "images" / Path(pages[0]).name
        txt_dst = OUT / "truth" / Path(row["truth_file"]).name
        shutil.copyfile(img_src, img_dst)
        shutil.copyfile(txt_src, txt_dst)

        manifest.append({
            "pair_id": row["pair_id"],
            "image": str(img_dst),
            "truth": str(txt_dst),
            "num_pages": row["num_pages"],
            "contributor": row["contributor"],
        })
        picked += 1

    man = OUT / "manifest.csv"
    with man.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(manifest[0].keys()))
        w.writeheader()
        w.writerows(manifest)

    print(f"pulled {picked} pairs -> {OUT}")
    print(f"manifest: {man}")
    print(f"source: {REPO}@{REVISION[:7]} (CC-BY-4.0)")


if __name__ == "__main__":
    main()
