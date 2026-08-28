"""Printable blank form templates for the held-out set (PRD 12.1).

Generates A4 300-DPI blanks for the four amr_flow_v1 page types as one PDF:
print, hand-fill with FABRICATED data, photograph, transcribe.

These are generic stand-ins. If the real study CRFs or Zambia MoH / WHO
register layouts are available, print those instead -- the held-out set should
look like the forms the pipeline will actually face.

    uv run python scripts/make_heldout_templates.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 2480, 3508          # A4 @ 300 DPI
INK = (30, 30, 30)
OUT = Path("samples/heldout/templates.pdf")

F_TITLE = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
F_BODY = "/System/Library/Fonts/Supplemental/Arial.ttf"


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size)


def page() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGB", (W, H), "white")
    return im, ImageDraw.Draw(im)


def title(d, text):
    d.text((160, 140), text, font=_font(F_TITLE, 88), fill=INK)
    d.line((160, 270, W - 160, 270), fill=INK, width=5)


def labeled_line(d, y, label, x=160, line_from=None, line_to=None, size=56):
    f = _font(F_BODY, size)
    d.text((x, y), label, font=f, fill=INK)
    lf = line_from if line_from is not None else x + int(d.textlength(label, f)) + 30
    d.line((lf, y + size + 8, line_to or W - 160, y + size + 8), fill=INK, width=3)


def section(d, y, text):
    d.text((160, y), text, font=_font(F_TITLE, 60), fill=INK)


def checkbox_row(d, y, label, options, x0=860, step=380):
    d.text((160, y), label, font=_font(F_BODY, 56), fill=INK)
    x = x0
    for opt in options:
        d.rectangle((x, y - 4, x + 64, y + 60), outline=INK, width=4)
        d.text((x + 84, y), opt, font=_font(F_BODY, 56), fill=INK)
        x += step
    return y


def demographics(d, y0):
    labeled_line(d, y0, "Patient name:", line_from=700, line_to=1700)
    labeled_line(d, y0, "Age:", x=1780, line_from=1930, line_to=2320)
    labeled_line(d, y0 + 140, "Hospital number:", line_from=700, line_to=1700)
    labeled_line(d, y0 + 140, "Sex:", x=1780, line_from=1930, line_to=2320)
    labeled_line(d, y0 + 280, "Date:", line_from=700, line_to=1700)
    return y0 + 420


def grid(d, y0, headers, widths, n_rows, row_h=140):
    xs = [160]
    for w_ in widths:
        xs.append(xs[-1] + w_)
    f = _font(F_BODY, 52)
    for x, htxt in zip(xs, headers):
        d.text((x + 20, y0 + 24), htxt, font=f, fill=INK)
    for r in range(n_rows + 2):
        d.line((xs[0], y0 + r * row_h, xs[-1], y0 + r * row_h), fill=INK, width=3)
    for x in xs:
        d.line((x, y0, x, y0 + (n_rows + 1) * row_h), fill=INK, width=3)
    return y0 + (n_rows + 1) * row_h


def prescription() -> Image.Image:
    im, d = page()
    title(d, "PRESCRIPTION NOTE")
    y = demographics(d, 400)
    labeled_line(d, y, "Diagnosis:", line_from=700, line_to=2320)
    section(d, y + 200, "Rx")
    grid(d, y + 300, ["Drug (name and form)", "Dose", "Frequency", "Duration"],
         [900, 420, 480, 360], 8)
    labeled_line(d, H - 400, "Prescriber:", line_from=700, line_to=1600)
    labeled_line(d, H - 400, "Signature:", x=1700, line_from=2000, line_to=2320)
    return im


def vitals() -> Image.Image:
    im, d = page()
    title(d, "NURSING OBSERVATION CHART")
    y = demographics(d, 400)
    labeled_line(d, y, "Ward:", line_from=700, line_to=1700)
    labeled_line(d, y + 140, "Diagnosis:", line_from=700, line_to=2320)
    grid(d, y + 360, ["Date", "Time", "Temp (°C)", "Pulse (bpm)",
                      "Resp (cpm)", "BP (mmHg)"],
         [460, 340, 340, 380, 340, 300], 12)
    return im


def lab_request() -> Image.Image:
    im, d = page()
    title(d, "LABORATORY REQUEST FORM")
    y = demographics(d, 400)
    checkbox_row(d, y, "Specimen type:", ["Blood", "Urine", "Stool", "CSF"])
    section(d, y + 180, "Investigations requested")
    for i in range(5):
        labeled_line(d, y + 300 + i * 130, f"{i + 1}.", line_from=320,
                     line_to=2320)
    section(d, y + 1050, "Clinical details")
    for i in range(3):
        d.line((160, y + 1220 + i * 130, 2320, y + 1220 + i * 130),
               fill=INK, width=3)
    checkbox_row(d, y + 1680, "Priority:", ["Routine", "Urgent"], x0=700)
    labeled_line(d, H - 400, "Requested by:", line_from=750, line_to=1700)
    return im


def visit_note() -> Image.Image:
    im, d = page()
    title(d, "PATIENT VISIT NOTE")
    y = demographics(d, 400)
    for label, lines in [("Chief complaint", 2), ("History", 5),
                         ("Examination", 4), ("Assessment", 2), ("Plan", 3)]:
        section(d, y, label)
        for i in range(lines):
            d.line((160, y + 170 + i * 130, 2320, y + 170 + i * 130),
                   fill=INK, width=3)
        y += 190 + lines * 130
    return im


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pages = [prescription(), vitals(), lab_request(), visit_note()]
    pages[0].save(OUT, save_all=True, append_images=pages[1:],
                  resolution=300.0)
    print(f"wrote {OUT} ({len(pages)} templates: prescription, vitals chart, "
          f"lab request, visit note)")


if __name__ == "__main__":
    main()
