"""Engine interfaces (PRD 5.1).

Two abstractions, so either side can be swapped or disabled by config:

  LayoutEngine     -- finds regions on a page and tags printed vs handwritten.
  ExtractionEngine -- reads an image and returns JSON conforming to a schema.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EngineHealth:
    ok: bool
    backend: str
    detail: str
    model: str | None = None
    latency_ms: float | None = None


@dataclass
class DetectedRegion:
    """A region on a page, in page pixel coordinates."""

    bbox: tuple[int, int, int, int]      # x0, y0, x1, y1
    region_type: str = "text"            # text | table | figure | checkbox | ...
    is_handwritten: bool | None = None
    reading_order: int | None = None
    text: str | None = None              # OCR text when the engine provides it
    confidence: float | None = None


@dataclass
class RawCompletion:
    """What came back from the model, before any parsing."""

    text: str
    model: str
    latency_ms: float
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    structured: bool = False             # True if grammar-constrained decoding


class ExtractionEngine(ABC):
    """Reads images, emits text that should be JSON."""

    name: str = "abstract"
    version: str = "0"

    @abstractmethod
    def health(self) -> EngineHealth:
        """Cheap reachability check for `scribe status`."""

    @abstractmethod
    def complete(
        self,
        *,
        system: str,
        user: str,
        images: list[Path],
        json_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> RawCompletion:
        """One chat completion with images attached.

        When `json_schema` is given and the backend supports constrained
        decoding, the output is forced to conform. Callers must still handle
        malformed output -- the repair path exists because not every backend
        honours this (PRD 7.2).
        """


class LayoutEngine(ABC):
    """Finds regions on a page."""

    name: str = "abstract"
    version: str = "0"

    @abstractmethod
    def health(self) -> EngineHealth: ...

    @abstractmethod
    def detect(self, image_path: Path) -> list[DetectedRegion]: ...

    def locate_fields(
        self, image_path: Path, fields: list[tuple[str, str]]
    ) -> dict[str, tuple[int, int, int, int]]:
        """Field-aware localization: (field_name, description) pairs in, a
        bbox in page pixels per located field out. Fields the engine cannot
        place are simply absent -- the extract stage falls back to the whole
        page for those. Default: locate nothing (whole-page mode)."""
        return {}


class WholePageLayout(LayoutEngine):
    """The v0 baseline: no layout model, one region covering the page.

    This is what `layout_engine: none` selects. Every field is extracted from
    the full page image (PRD 10.1, whole-page mode).
    """

    name = "none"
    version = "1"

    def health(self) -> EngineHealth:
        return EngineHealth(
            ok=True,
            backend="none",
            detail="whole-page mode; no layout model loaded",
        )

    def detect(self, image_path: Path) -> list[DetectedRegion]:
        from PIL import Image

        with Image.open(image_path) as im:
            w, h = im.size
        return [
            DetectedRegion(
                bbox=(0, 0, w, h),
                region_type="page",
                is_handwritten=None,
                reading_order=0,
            )
        ]
