"""Qwen-grounding layout engine (M1b).

Uses the same local VLM server as extraction to localize schema fields: one
call per page returns a bbox for every field at once, then each field is read
from its crop instead of the full page.

Why this engine exists on the Mac: the M0 findings (docs/bench.md) ruled out
GPU-accelerated PaddleOCR-VL (CPU-only wheels) and left dots.ocr as a second
PyTorch stack competing for unified memory. Qwen3-VL grounding needs no new
dependencies, shares the resident model, and returns boxes in its documented
0-1000 normalized coordinate space.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from scribe.engines.base import (
    DetectedRegion,
    EngineHealth,
    ExtractionEngine,
    LayoutEngine,
)
from scribe.stages.jsonrepair import parse_model_json

_SYSTEM = "You locate regions on scanned clinical forms. Output only JSON."

_USER_TEMPLATE = """\
Locate each of the following regions on the page. For every region you can
find, return its bounding box as bbox_2d = [x1, y1, x2, y2] in this image's
coordinate space. The box must enclose the ENTIRE region including any
handwritten overflow. For a table, include the header row and every data row.
Omit regions that are not present on this page -- never invent a box.

Regions:
{fields}

Return JSON: {{"regions": [{{"label": "...", "bbox_2d": [x1, y1, x2, y2]}}]}}
"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "regions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "bbox_2d": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                },
                "required": ["label", "bbox_2d"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["regions"],
    "additionalProperties": False,
}


class QwenGroundingLayout(LayoutEngine):
    name = "qwen_grounding"
    version = "1"

    def __init__(self, engine: ExtractionEngine, max_tokens: int = 1200):
        self._engine = engine
        self.max_tokens = max_tokens

    def health(self) -> EngineHealth:
        h = self._engine.health()
        return EngineHealth(
            ok=h.ok,
            backend=self.name,
            model=h.model,
            latency_ms=h.latency_ms,
            detail=f"grounding via extraction engine: {h.detail}",
        )

    def detect(self, image_path: Path) -> list[DetectedRegion]:
        # Generic detection is not this engine's job; field-aware localization
        # below is. Whole page as the single fallback region.
        with Image.open(image_path) as im:
            w, h = im.size
        return [DetectedRegion(bbox=(0, 0, w, h), region_type="page")]

    def locate_fields(
        self, image_path: Path, fields: list[tuple[str, str]]
    ) -> dict[str, tuple[int, int, int, int]]:
        if not fields:
            return {}
        listing = "\n".join(
            f"- label '{name}': {desc}" for name, desc in fields
        )
        completion = self._engine.complete(
            system=_SYSTEM,
            user=_USER_TEMPLATE.format(fields=listing),
            images=[image_path],
            json_schema=_SCHEMA,
            max_tokens=self.max_tokens,
        )
        parsed = parse_model_json(completion.text)
        if not parsed:
            return {}

        with Image.open(image_path) as im:
            w, h = im.size
        wanted = {name for name, _d in fields}
        out: dict[str, tuple[int, int, int, int]] = {}
        for region in parsed.get("regions") or []:
            label_raw = str(region.get("label") or "")
            box = region.get("bbox_2d")
            # Some models echo the whole listing line back as the label
            # ("label 'patient_name': the handwritten value ...") -- match by
            # containment, but only when exactly one field name matches.
            if label_raw in wanted:
                label = label_raw
            else:
                hits = [n for n in wanted if n in label_raw]
                label = hits[0] if len(hits) == 1 else None
            if label is None or not isinstance(box, list) or len(box) != 4:
                continue
            try:
                x1, y1, x2, y2 = (float(v) for v in box)
            except (TypeError, ValueError):
                continue
            # Qwen3-VL grounding uses 0-1000 normalized coordinates.
            px = (
                round(x1 * w / 1000), round(y1 * h / 1000),
                round(x2 * w / 1000), round(y2 * h / 1000),
            )
            if px[2] <= px[0] or px[3] <= px[1]:
                continue
            out[label] = px
        return out


def crop_region(
    image_path: Path,
    bbox: tuple[int, int, int, int],
    out_path: Path,
    margin_px: int = 24,
) -> Path:
    """Save a margin-padded crop; returns out_path."""
    with Image.open(image_path) as im:
        w, h = im.size
        x1, y1, x2, y2 = bbox
        box = (max(0, x1 - margin_px), max(0, y1 - margin_px),
               min(w, x2 + margin_px), min(h, y2 + margin_px))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        im.crop(box).save(out_path, "PNG")
    return out_path
