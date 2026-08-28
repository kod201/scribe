"""Guards on the M0 artifacts: the schema loads, and the gold set agrees with it.

The gold set is hand-curated, so the failure mode is drift -- a field renamed in
the schema and not in gold, or a gold value that the schema would reject.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scribe.schema import SCALAR_TYPES, Schema, load_schema

SCHEMA_PATH = Path("schemas/amr_flow_v1.yaml")
GOLD_PATH = Path("samples/flow/gold.csv")


@pytest.fixture(scope="module")
def schema() -> Schema:
    return load_schema(SCHEMA_PATH)


@pytest.fixture(scope="module")
def gold() -> dict[str, dict[str, object]]:
    rows = list(csv.DictReader(GOLD_PATH.read_text().splitlines()))
    out: dict[str, dict[str, object]] = {}
    for r in rows:
        out.setdefault(r["pair_id"], {})[r["field_name"]] = json.loads(r["gold_json"])
    return out


def test_schema_loads(schema: Schema) -> None:
    assert schema.schema_id == "amr_flow_v1"
    assert schema.page_type_ids == [
        "visit_note", "vitals_chart", "prescription", "lab_request"
    ]


def test_every_field_has_an_extract_hint(schema: Schema) -> None:
    """A field with no hint is a field the model will guess at."""
    missing = [f.name for f in schema.fields if not f.extract_hint]
    assert not missing, f"fields without extract_hint: {missing}"


def test_table_columns_are_scalar(schema: Schema) -> None:
    for f in schema.fields:
        for col in f.columns or []:
            assert col.type in SCALAR_TYPES


def test_gold_field_names_exist_in_schema(schema: Schema, gold) -> None:
    known = {f.name for f in schema.fields}
    for pair_id, fields in gold.items():
        unknown = set(fields) - known
        assert not unknown, f"{pair_id} has fields not in the schema: {unknown}"


def test_gold_respects_page_type_scoping(schema: Schema, gold) -> None:
    """A page must only carry fields valid for its own document_type."""
    for pair_id, fields in gold.items():
        doc_type = fields["document_type"]
        allowed = {f.name for f in schema.fields_for(doc_type)}
        stray = set(fields) - allowed
        assert not stray, f"{pair_id} ({doc_type}) carries out-of-scope: {stray}"


def test_gold_covers_every_applicable_field(schema: Schema, gold) -> None:
    """Missing a field in gold silently drops it from eval, so require them all."""
    for pair_id, fields in gold.items():
        expected = {f.name for f in schema.fields_for(fields["document_type"])}
        assert not expected - set(fields), (
            f"{pair_id} is missing gold for: {sorted(expected - set(fields))}"
        )


def test_gold_scalar_values_satisfy_constraints(schema: Schema, gold) -> None:
    for pair_id, fields in gold.items():
        for name, value in fields.items():
            if value is None:
                continue
            f = schema.field(name)
            if f.type == "enum":
                assert value in (f.values or []), f"{pair_id}.{name}={value!r}"
            elif f.type == "integer":
                assert isinstance(value, int)
                if f.min is not None:
                    assert value >= f.min, f"{pair_id}.{name}={value}"
                if f.max is not None:
                    assert value <= f.max, f"{pair_id}.{name}={value}"
            elif f.type in ("string", "free_text"):
                assert isinstance(value, str)
                if f.max_length:
                    assert len(value) <= f.max_length, (
                        f"{pair_id}.{name} is {len(value)} chars, "
                        f"max_length is {f.max_length}"
                    )


def test_gold_table_rows_use_declared_columns(schema: Schema, gold) -> None:
    for pair_id, fields in gold.items():
        for name, value in fields.items():
            f = schema.field(name)
            if f.type != "table":
                continue
            assert isinstance(value, list), f"{pair_id}.{name} must be a list"
            cols = {c.name for c in f.columns or []}
            for i, row in enumerate(value):
                assert set(row) == cols, (
                    f"{pair_id}.{name}[{i}] columns {sorted(row)} != {sorted(cols)}"
                )
            assert len(value) <= f.max_rows


def test_gold_table_cell_ranges(schema: Schema, gold) -> None:
    for pair_id, fields in gold.items():
        for name, value in fields.items():
            f = schema.field(name)
            if f.type != "table":
                continue
            by_name = {c.name: c for c in f.columns or []}
            for i, row in enumerate(value):
                for col_name, cell in row.items():
                    if cell is None:
                        continue
                    c = by_name[col_name]
                    if c.min is not None:
                        assert cell >= c.min, f"{pair_id}.{name}[{i}].{col_name}={cell}"
                    if c.max is not None:
                        assert cell <= c.max, f"{pair_id}.{name}[{i}].{col_name}={cell}"


def test_flow_set_has_all_four_page_types(gold) -> None:
    seen = {f["document_type"] for f in gold.values()}
    assert seen == {"visit_note", "vitals_chart", "prescription", "lab_request"}


def test_synthetic_pages_are_present(gold) -> None:
    """The zero-dependency smoke test must not silently disappear."""
    assert {"SYN_001", "SYN_002", "SYN_003"} <= set(gold)
    for pid in ("SYN_001", "SYN_002", "SYN_003"):
        assert Path(f"samples/flow/images/{pid}.png").exists()


def test_null_cases_are_represented(gold) -> None:
    """The flow set exists to exercise the review path, so it must contain
    fields that are legitimately unreadable or absent."""
    nulls = sum(1 for f in gold.values() for v in f.values() if v is None)
    assert nulls >= 30, f"only {nulls} null gold values; too few to test flagging"
    # The non-numeric age trap specifically.
    assert gold["SYN_003"]["patient_age_years"] is None
    assert gold["AMR_003"]["patient_age_years"] is None
    # The smudged cell and the blank cell on the synthetic vitals chart.
    assert gold["SYN_002"]["vitals"][1]["temp_c"] is None
    assert gold["SYN_002"]["vitals"][2]["pulse_bpm"] is None
