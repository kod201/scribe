"""Schema specification: YAML in, typed field definitions out (PRD 6).

Swapping forms means editing a schema file, not code. Field types are the PRD 6
set plus `table`, added because the AMR nursing observation chart is a repeating
vitals grid that no scalar type can express. A `table` field declares `columns`,
each of which is itself a scalar field definition.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

FieldType = Literal[
    "string",
    "integer",
    "float",
    "date",
    "datetime",
    "enum",
    "boolean",
    "checkbox_group",
    "free_text",
    "table",
]

SCALAR_TYPES = {
    "string",
    "integer",
    "float",
    "date",
    "datetime",
    "enum",
    "boolean",
    "free_text",
}


class PageType(BaseModel):
    id: str
    detect_hint: str | None = None


class FieldDef(BaseModel):
    """One target field. Every field may override the global review threshold."""

    name: str
    type: FieldType
    required: bool = False
    allow_null: bool = True
    page_type: str | None = None

    # Constraints
    min: float | None = None
    max: float | None = None
    regex: str | None = None
    values: list[str] | None = None          # enum / checkbox_group members
    format: str | None = None                # strftime pattern for date/datetime
    max_length: int | None = None

    # Prompting
    locate_hint: str | None = None
    extract_hint: str | None = None

    # Routing
    review_threshold: float | None = None

    # table only
    columns: list["FieldDef"] | None = None
    max_rows: int = 40

    @model_validator(mode="after")
    def _check_type_constraints(self) -> "FieldDef":
        if self.type == "enum" and not self.values:
            raise ValueError(f"field '{self.name}': enum requires `values`")
        if self.type == "checkbox_group" and not self.values:
            raise ValueError(f"field '{self.name}': checkbox_group requires `values`")
        if self.type == "table":
            if not self.columns:
                raise ValueError(f"field '{self.name}': table requires `columns`")
            for c in self.columns:
                if c.type not in SCALAR_TYPES:
                    raise ValueError(
                        f"field '{self.name}': table column '{c.name}' has "
                        f"non-scalar type '{c.type}'; nested tables are not supported"
                    )
        elif self.columns:
            raise ValueError(f"field '{self.name}': `columns` is only valid on tables")
        if self.required and self.type != "table" and self.min is not None \
                and self.max is not None and self.min > self.max:
            raise ValueError(f"field '{self.name}': min > max")
        return self

    def threshold(self, default: float) -> float:
        return self.review_threshold if self.review_threshold is not None else default


class CrossFieldRule(BaseModel):
    rule: str
    on_fail: str = "flag_both"
    message: str | None = None


class Schema(BaseModel):
    schema_id: str
    version: int = 1
    description: str | None = None
    page_types: list[PageType] = Field(default_factory=list)
    # Routing fallback when the page-type classifier returns null (models
    # sometimes refuse the classification call even while extraction calls
    # succeed). None keeps the old behaviour: unclassified pages run every
    # field.
    default_page_type: str | None = None
    fields: list[FieldDef]
    cross_field_rules: list[CrossFieldRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "Schema":
        names = [f.name for f in self.fields]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate field names: {sorted(dupes)}")
        known = {p.id for p in self.page_types}
        for f in self.fields:
            if f.page_type and f.page_type not in known:
                raise ValueError(
                    f"field '{f.name}' references unknown page_type '{f.page_type}'"
                )
        if self.default_page_type and self.default_page_type not in known:
            raise ValueError(
                f"default_page_type '{self.default_page_type}' is not a"
                f" declared page_type"
            )
        return self

    def field(self, name: str) -> FieldDef:
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(name)

    def fields_for(self, page_type: str | None) -> list[FieldDef]:
        """Fields that apply to a page. Fields with no `page_type` are global."""
        if page_type is None:
            return list(self.fields)
        return [f for f in self.fields if f.page_type in (None, page_type)]

    @property
    def page_type_ids(self) -> list[str]:
        return [p.id for p in self.page_types]


def load_schema(path: Path | str) -> Schema:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No schema at {p}")
    data: dict[str, Any] = yaml.safe_load(p.read_text()) or {}
    return Schema.model_validate(data)


def find_schema(schema_id: str, search_dir: Path | str = "schemas") -> Schema:
    """Resolve a schema by its schema_id across the schemas directory."""
    d = Path(search_dir)
    for p in sorted(d.glob("*.y*ml")):
        try:
            s = load_schema(p)
        except Exception:
            continue
        if s.schema_id == schema_id:
            return s
    raise KeyError(f"No schema with schema_id '{schema_id}' in {d}/")


def list_schemas(search_dir: Path | str = "schemas") -> list[tuple[Path, Schema]]:
    out = []
    for p in sorted(Path(search_dir).glob("*.y*ml")):
        try:
            out.append((p, load_schema(p)))
        except Exception:
            continue
    return out


FieldDef.model_rebuild()
