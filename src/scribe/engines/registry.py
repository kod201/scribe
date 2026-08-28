"""Config -> engine instances. The only place backend names are resolved."""

from __future__ import annotations

from scribe.config import Config
from scribe.engines.base import ExtractionEngine, LayoutEngine, WholePageLayout

_EXTRACTION_BACKENDS = {"mlx", "vllm"}


def build_verify_engine(cfg: Config) -> ExtractionEngine | None:
    """The verify pass's engine, when a distinct one is configured."""
    if cfg.verify_engine is None:
        return None
    return _build(cfg.verify_engine)


def build_extraction_engine(cfg: Config) -> ExtractionEngine:
    return _build(cfg.extraction_engine)


def _build(ec) -> ExtractionEngine:
    if ec.backend not in _EXTRACTION_BACKENDS:
        raise ValueError(
            f"Unknown extraction backend '{ec.backend}'. "
            f"Known: {sorted(_EXTRACTION_BACKENDS)}"
        )
    # Both backends are OpenAI-compatible HTTP servers; they differ only in how
    # they are launched (see `scribe serve`).
    from scribe.engines.openai_compat import OpenAICompatEngine

    return OpenAICompatEngine(
        server_url=ec.server_url,
        model=ec.model,
        backend=ec.backend,
        revision=ec.revision,
        max_tokens=ec.max_tokens,
        temperature=ec.temperature,
        timeout_s=ec.request_timeout_s,
        structured_output=ec.structured_output,
    )


def build_layout_engine(cfg: Config) -> LayoutEngine:
    name = (cfg.layout_engine or "none").lower()
    if name in ("none", "whole_page", "whole-page"):
        return WholePageLayout()
    if name == "qwen_grounding":
        from scribe.engines.grounding import QwenGroundingLayout

        return QwenGroundingLayout(build_extraction_engine(cfg))
    # PaddleOCR-VL / dots.ocr are CUDA-box work (docs/bench.md, M0 findings).
    # Kept as an explicit error so a typo in config.yaml never silently
    # degrades to whole-page mode.
    raise NotImplementedError(
        f"Layout engine '{name}' is not available. Known: none, qwen_grounding."
    )
