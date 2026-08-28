"""Typed view over config.yaml.

Model names, thresholds and paths live in the YAML file only; nothing in the
codebase hard-wires an engine (PRD 16).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path("config.yaml")


class ExtractionEngineConfig(BaseModel):
    backend: str = "mlx"
    model: str
    revision: str | None = None
    max_tokens: int = 512
    temperature: float = 0.0
    server_url: str = "http://127.0.0.1:8080/v1"
    request_timeout_s: float = 300.0
    structured_output: bool = True
    # Extra flags appended verbatim to the serve command (backend-specific,
    # e.g. vLLM's --max-model-len or --gpu-memory-utilization).
    extra_serve_args: list[str] = Field(default_factory=list)


class IngestConfig(BaseModel):
    target_dpi: int = 200
    deskew: bool = True
    denoise: bool = True
    max_edge_px: int = 2400


class PathsConfig(BaseModel):
    inbox: Path = Path("./data/inbox")
    work: Path = Path("./data/work")
    db: Path = Path("./data/scribe.sqlite")
    exports: Path = Path("./data/exports")

    def mkdirs(self) -> None:
        for p in (self.inbox, self.work, self.exports, self.db.parent):
            p.mkdir(parents=True, exist_ok=True)


class RedcapConfig(BaseModel):
    """REDCap import adapter (M5). The API token NEVER lives in config; it is
    read from the environment variable named by token_env at export time."""

    api_url: str | None = None            # e.g. https://redcap.example.org/api/
    token_env: str = "REDCAP_API_TOKEN"
    record_id_field: str = "record_id"
    overwrite: bool = False               # False -> 'normal', True -> 'overwrite'
    field_map: dict[str, str] = Field(default_factory=dict)
    table_fields_as_json: bool = True     # serialize tables into their field
    skip_unmapped: bool = False           # True -> send only field_map fields


class SecurityConfig(BaseModel):
    assert_offline: bool = True
    allow_hosts: list[str] = Field(default_factory=lambda: ["127.0.0.1", "localhost"])


class Config(BaseModel):
    layout_engine: str = "none"
    # When a layout engine is active, crop-extract only these field types;
    # everything else keeps full-page context. null/empty = crop everything.
    # The M1b comparison (docs/bench.md) motivates the split: crops win on
    # tables/dates/enums, full pages win on header-labeled scalars and prose.
    crop_field_types: list[str] | None = None
    # Second read from the complementary source (crop <-> whole page) for
    # fields the first read did NOT flag; disagreement flags the field and
    # halves its composite. Operationalizes PRD 7.3's second pass -- the
    # offline analysis in docs/bench.md M4 showed model confidence alone
    # cannot separate right from wrong, but cross-source agreement can.
    verify_pass: bool = False
    # Optional second engine for the verify pass. A DIFFERENT model
    # decorrelates the errors the primary and verifier share -- same-model
    # verification cannot catch a bias both reads have (bench.md M4 verdict).
    # None = verify with the primary engine (cross-source only).
    verify_engine: ExtractionEngineConfig | None = None
    extraction_engine: ExtractionEngineConfig
    review_threshold_default: float = 0.85
    crop_margin_px: int = 24
    parallelism: int = 1
    ingest: IngestConfig = Field(default_factory=IngestConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    redcap: RedcapConfig = Field(default_factory=RedcapConfig)

    # Where this config was loaded from, for provenance in status output.
    source_path: Path | None = None


def load_config(path: Path | str | None = None) -> Config:
    """Load config.yaml. Raises if the file is missing -- there is no implicit
    default model, on purpose."""
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"No config at {p}. Copy config.yaml from the repo root or pass --config."
        )
    data = yaml.safe_load(p.read_text()) or {}
    cfg = Config.model_validate(data)
    cfg.source_path = p.resolve()
    return cfg
