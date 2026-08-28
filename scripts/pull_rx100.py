"""Pull the external prescription set -> samples/rx100/ (images + gold.csv).

Dataset: chaithanyakota/100-handwritten-medical-records (CC-BY-ND-4.0).
ND means: evaluate freely, publish results freely, never redistribute
modified copies of the data. Images therefore stay out of git (see
.gitignore) exactly like the AMR pull.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from huggingface_hub import hf_hub_download

REPO = "chaithanyakota/100-handwritten-medical-records"
REVISION = "afcca9f163561af54fcd145003e550d2d320aafb"
OUT = Path("samples/rx100")


def main() -> None:
    import pyarrow.parquet as pq
    from PIL import Image

    (OUT / "images").mkdir(parents=True, exist_ok=True)
    path = hf_hub_download(REPO, "data/train-00000-of-00001.parquet",
                           repo_type="dataset", revision=REVISION)
    t = pq.read_table(path)
    images = t.column("image").to_pylist()
    meds = t.column("medicines").to_pylist()

    rows = []
    for i, (img, med_str) in enumerate(zip(images, meds), start=1):
        pid = f"RX_{i:03d}"
        im = Image.open(io.BytesIO(img["bytes"])).convert("RGB")
        im.save(OUT / "images" / f"{pid}.png", "PNG")
        med_rows = [{"medicine": m.strip()}
                    for m in str(med_str).split(",") if m.strip()]
        rows.append({
            "pair_id": pid, "page_no": 1, "field_name": "medicines",
            "gold_json": json.dumps(med_rows, ensure_ascii=False),
        })

    with (OUT / "gold.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["pair_id", "page_no", "field_name",
                                           "gold_json"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} pages -> {OUT}")
    print(f"source: {REPO}@{REVISION[:7]} (CC-BY-ND-4.0)")


if __name__ == "__main__":
    main()
