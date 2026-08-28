"""Engine interfaces and their concrete backends.

Nothing outside this package may name a model. Callers ask the registry for an
engine and get whatever config.yaml selected (PRD 16).
"""

from scribe.engines.base import (
    DetectedRegion,
    EngineHealth,
    ExtractionEngine,
    LayoutEngine,
    RawCompletion,
)
from scribe.engines.registry import build_extraction_engine, build_layout_engine

__all__ = [
    "DetectedRegion",
    "EngineHealth",
    "ExtractionEngine",
    "LayoutEngine",
    "RawCompletion",
    "build_extraction_engine",
    "build_layout_engine",
]
