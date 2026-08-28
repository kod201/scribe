"""Ruled-line detection for the review UI's row guides.

Ledger pages are dominated by long horizontal rules. Reviewers matching a
table row_no to the image need to count rows; drawing the detected rules as
numbered strips makes that a glance instead of a squint. Best effort by
design: returning [] (no guides) is always acceptable, wrong guides are not,
so the thresholds below prefer silence over noise.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def detect_row_lines(image_path: Path, max_width: int = 1200) -> list[float]:
    """y-positions of horizontal ruled lines as fractions of image height."""
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return []
    h, w = img.shape
    if w > max_width:
        s = max_width / w
        img = cv2.resize(img, (max_width, round(h * s)),
                         interpolation=cv2.INTER_AREA)
        h, w = img.shape

    # Ink (incl. faint blue rules) is darker than paper; adaptive threshold
    # tolerates the uneven lighting of phone photos.
    ink = cv2.adaptiveThreshold(
        img, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 10,
    )
    # Crumpled pages make the rules wavy, so a long straight kernel finds
    # nothing. Instead: keep moderately long segments, then dilate a few
    # pixels vertically so a wavy rule's segments merge into one band.
    klen = max(w // 16, 40)
    seg = cv2.erode(
        ink, cv2.getStructuringElement(cv2.MORPH_RECT, (klen, 1)))
    seg = cv2.dilate(
        seg, cv2.getStructuringElement(cv2.MORPH_RECT, (klen, 7)))
    covered = (seg > 0).sum(axis=1)

    ys: list[int] = []
    thresh = w * 0.35
    y = 0
    while y < h:
        if covered[y] >= thresh:
            run = y
            while run < h and covered[run] >= thresh * 0.6:
                run += 1
            ys.append((y + run) // 2)
            y = run + 1
        else:
            y += 1

    if len(ys) < 4:
        return []
    # A ruled grid is roughly periodic. Sub-rules inside ledger rows make the
    # spacing alternate, so only clearly chaotic spacing is rejected.
    gaps = np.diff(ys)
    med = float(np.median(gaps))
    if med < 8 or float(np.percentile(gaps, 90)) > med * 4:
        return []
    return [round(v / h, 4) for v in ys]
