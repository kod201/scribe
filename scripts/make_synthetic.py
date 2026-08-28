"""Generate 3 synthetic handwritten pages -- a zero-dependency smoke test.

Unlike the AMR pull these need no network and their ground truth is exact by
construction, so they are the fastest way to tell "the pipeline is broken" from
"the model read it wrong" (PRD 10.1).

Each page deliberately carries a failure mode the review path must catch:
  SYN_001  clean prescription, everything legible -- the happy path.
  SYN_002  vitals chart with one smudged cell and one blank cell.
  SYN_003  lab request with age written "Ad", no specimen ticked, low contrast.

    uv run python scripts/make_synthetic.py
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path("samples/flow")
HAND = "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf"
HAND_ALT = "/System/Library/Fonts/Supplemental/Chalkduster.ttf"
PRINT = "/System/Library/Fonts/Supplemental/Arial.ttf"

W, H = 1700, 2200
INK = (28, 32, 78)          # blue-black biro
PRINT_INK = (35, 35, 35)


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size)


def _paper() -> Image.Image:
    """Off-white paper with faint noise, so the page is not synthetically clean."""
    rng = np.random.default_rng(20260819)
    base = rng.normal(246, 3.2, (H, W, 3)).clip(200, 255).astype(np.uint8)
    return Image.fromarray(base, "RGB")


def _smudge(img: Image.Image, box: tuple[int, int, int, int], radius: float = 4.5):
    """Blur a rectangle so the text under it is genuinely hard to read."""
    region = img.crop(box).filter(ImageFilter.GaussianBlur(radius))
    img.paste(region, box)


def _finish(img: Image.Image, path: Path, contrast: float = 1.0) -> None:
    if contrast != 1.0:
        arr = np.asarray(img).astype(np.float32)
        arr = 255 - (255 - arr) * contrast
        img = Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGB")
    img = img.rotate(-0.7, resample=Image.BICUBIC, fillcolor=(246, 246, 244))
    img.save(path, "PNG")
    print(f"  wrote {path}")


# ---------------------------------------------------------------------------


def page_prescription(path: Path) -> None:
    img = _paper()
    d = ImageDraw.Draw(img)
    hd, lbl, hand = _font(PRINT, 62), _font(PRINT, 40), _font(HAND, 52)

    d.text((90, 90), "PRESCRIPTION NOTE", font=hd, fill=PRINT_INK)
    d.line((90, 175, W - 90, 175), fill=PRINT_INK, width=3)

    rows = [
        ("Patient Name:", "Ngozi Abara"),
        ("Age:", "34 years"),
        ("Sex:", "Female"),
        ("Hospital No:", "SYN/001/26"),
        ("Date:", "14/04/2026"),
    ]
    y = 240
    for label, value in rows:
        d.text((100, y), label, font=lbl, fill=PRINT_INK)
        d.text((520, y - 8), value, font=hand, fill=INK)
        y += 95

    d.text((100, y + 30), "Diagnosis:", font=lbl, fill=PRINT_INK)
    d.text((520, y + 22), "Community acquired pneumonia", font=hand, fill=INK)

    d.text((100, y + 150), "Rx", font=_font(PRINT, 52), fill=PRINT_INK)
    meds = [
        "1.  Tab Amoxicillin 500mg  tds  x 7/7",
        "2.  Tab Paracetamol 500mg  qds  x 5/7",
        "3.  Syr Ascorbic acid 100mg  daily  x 10/7",
    ]
    yy = y + 230
    for m in meds:
        d.text((140, yy), m, font=hand, fill=INK)
        yy += 100

    d.text((100, yy + 90), "Prescriber:", font=lbl, fill=PRINT_INK)
    d.text((520, yy + 82), "Dr. Ifeoma Nwosu", font=hand, fill=INK)
    _finish(img, path)


def page_vitals(path: Path) -> None:
    img = _paper()
    d = ImageDraw.Draw(img)
    hd, lbl = _font(PRINT, 58), _font(PRINT, 36)
    hand, hand_s = _font(HAND, 48), _font(HAND, 44)

    d.text((90, 90), "NURSING OBSERVATION CHART", font=hd, fill=PRINT_INK)
    d.line((90, 170, W - 90, 170), fill=PRINT_INK, width=3)

    for i, (label, value) in enumerate([
        ("Patient name:", "Tunde Balogun"),
        ("Age/Sex:", "57/M"),
        ("Hospital number:", "SYN/002/26"),
        ("Ward:", "Male medical ward"),
        ("Diagnosis:", "Congestive cardiac failure"),
    ]):
        yy = 230 + i * 88
        d.text((100, yy), label, font=lbl, fill=PRINT_INK)
        d.text((600, yy - 8), value, font=hand, fill=INK)

    top = 720
    cols = [100, 460, 760, 1050, 1330, 1600]
    heads = ["Date", "Time", "Temp(C)", "Pulse", "Resp"]
    for x, htxt in zip(cols, heads):
        d.text((x + 12, top + 14), htxt, font=lbl, fill=PRINT_INK)

    data = [
        ("14/04/2026", "08:00", "38.6", "104", "24"),
        ("14/04/2026", "12:00", "38.1", "98", "22"),
        ("14/04/2026", "16:00", "37.8", "94", "20"),
        ("14/04/2026", "20:00", "37.4", "88", "19"),
        ("15/04/2026", "08:00", "37.1", "84", "18"),
    ]
    rh = 96
    for r in range(len(data) + 1):
        yy = top + r * rh
        d.line((cols[0], yy, cols[-1], yy), fill=PRINT_INK, width=2)
    d.line((cols[0], top + (len(data) + 1) * rh, cols[-1],
            top + (len(data) + 1) * rh), fill=PRINT_INK, width=2)
    for x in cols:
        d.line((x, top, x, top + (len(data) + 1) * rh), fill=PRINT_INK, width=2)

    for r, row in enumerate(data):
        yy = top + (r + 1) * rh + 20
        for c, cell in enumerate(row):
            # Row 3 pulse is left blank on purpose; row 2 temp gets smudged.
            if r == 2 and c == 3:
                continue
            d.text((cols[c] + 20, yy), cell, font=hand_s, fill=INK)

    _smudge(img, (cols[2] + 4, top + 2 * rh + 8, cols[3] - 4, top + 3 * rh - 8), 5.0)
    _finish(img, path)


def page_lab(path: Path) -> None:
    img = _paper()
    d = ImageDraw.Draw(img)
    hd, lbl = _font(PRINT, 58), _font(PRINT, 38)
    hand = _font(HAND_ALT, 46)

    d.text((90, 90), "LAB REQUEST FORM", font=hd, fill=PRINT_INK)
    d.line((90, 170, W - 90, 170), fill=PRINT_INK, width=3)

    for i, (label, value) in enumerate([
        ("Name:", "Chidi Eze"),
        ("Age:", "Ad"),                      # the non-numeric age trap
        ("Sex:", "M"),
        ("Hospital number:", "SYN/003/26"),
        ("Date:", "15 Apr, 2026"),           # needs normalising to 15/04/2026
    ]):
        yy = 240 + i * 92
        d.text((100, yy), label, font=lbl, fill=PRINT_INK)
        d.text((640, yy - 6), value, font=hand, fill=INK)

    d.text((100, 730), "Specimen type:", font=lbl, fill=PRINT_INK)
    bx = 640
    for name in ["Blood", "Urine", "Stool", "CSF"]:
        d.rectangle((bx, 726, bx + 40, 766), outline=PRINT_INK, width=3)
        d.text((bx + 56, 728), name, font=lbl, fill=PRINT_INK)
        bx += 250                            # every box left unticked

    d.text((100, 860), "Investigations requested:", font=lbl, fill=PRINT_INK)
    for i, t in enumerate(["Full Blood Count", "Malaria parasite test",
                           "Serum electrolytes, urea & creatinine"]):
        d.text((160, 950 + i * 92), f"{i + 1}.  {t}", font=hand, fill=INK)

    d.text((100, 1300), "Clinical details:", font=lbl, fill=PRINT_INK)
    d.text((160, 1390), "Fever 4/7, headache, joint pains.", font=hand, fill=INK)
    d.text((160, 1480), "?? Malaria", font=hand, fill=INK)

    d.text((100, 1650), "Requested by:", font=lbl, fill=PRINT_INK)
    d.text((640, 1642), "Dr. K. Musa", font=hand, fill=INK)

    _finish(img, path, contrast=0.62)        # faint photocopy


def main() -> None:
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    print("generating synthetic pages:")
    page_prescription(OUT / "images" / "SYN_001.png")
    page_vitals(OUT / "images" / "SYN_002.png")
    page_lab(OUT / "images" / "SYN_003.png")

    man = OUT / "manifest.csv"
    existing = []
    if man.exists():
        existing = [r for r in csv.DictReader(man.read_text().splitlines())
                    if not r["pair_id"].startswith("SYN_")]
    rows = existing + [
        {"pair_id": f"SYN_{i:03d}", "image": f"samples/flow/images/SYN_{i:03d}.png",
         "truth": "", "num_pages": "1", "contributor": "synthetic"}
        for i in (1, 2, 3)
    ]
    with man.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["pair_id", "image", "truth",
                                           "num_pages", "contributor"])
        w.writeheader()
        w.writerows(rows)
    print(f"manifest updated: {man} ({len(rows)} pages)")


if __name__ == "__main__":
    main()
