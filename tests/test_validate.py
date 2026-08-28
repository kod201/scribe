"""Validator tests, written before the validator (PRD 16).

The validator is the guarantee that a faithful-but-wrong model answer (the
smoke test's value:"Ad" for an integer age) never reaches the sink unflagged.
"""

from __future__ import annotations

import pytest

from scribe.schema import CrossFieldRule, FieldDef
from scribe.stages.validate import (
    ValidationOutcome,
    coerce_value,
    composite_confidence,
    evaluate_cross_field_rules,
    validate_field,
)

# ---------------------------------------------------------------------------
# coercion
# ---------------------------------------------------------------------------


def F(**kw) -> FieldDef:
    kw.setdefault("name", "f")
    kw.setdefault("type", "string")
    return FieldDef(**kw)


class TestCoerceInteger:
    fd = F(type="integer", min=0, max=120)

    def test_int_passes(self):
        assert coerce_value(34, self.fd) == (34, [])

    def test_numeric_string_coerces(self):
        assert coerce_value("34", self.fd) == (34, [])

    def test_non_numeric_string_fails(self):
        value, errors = coerce_value("Ad", self.fd)
        assert value is None and errors

    def test_trailing_unit_fails_not_guesses(self):
        # "34 years" is the model failing to normalise; coercion must not
        # silently strip units, that is the model's job to get right.
        value, errors = coerce_value("34 years", self.fd)
        assert value is None and errors

    def test_float_that_is_integral_coerces(self):
        assert coerce_value(34.0, self.fd) == (34, [])

    def test_float_with_fraction_fails(self):
        value, errors = coerce_value(34.5, self.fd)
        assert value is None and errors

    def test_bool_is_not_an_integer(self):
        value, errors = coerce_value(True, self.fd)
        assert value is None and errors

    def test_below_min_fails(self):
        value, errors = coerce_value(-1, self.fd)
        assert value is None and errors

    def test_above_max_fails(self):
        value, errors = coerce_value(200, self.fd)
        assert value is None and errors

    def test_null_passes_through(self):
        assert coerce_value(None, self.fd) == (None, [])


class TestCoerceFloat:
    fd = F(type="float", min=25.0, max=45.0)

    def test_float_passes(self):
        assert coerce_value(38.2, self.fd) == (38.2, [])

    def test_int_widens(self):
        assert coerce_value(38, self.fd) == (38.0, [])

    def test_string_number_coerces(self):
        assert coerce_value("38.2", self.fd) == (38.2, [])

    def test_range_enforced(self):
        assert coerce_value(98.6, self.fd)[0] is None  # Fahrenheit slip


class TestCoerceDate:
    fd = F(type="date", format="%d/%m/%Y")

    def test_conforming_date_passes(self):
        assert coerce_value("23/02/2025", self.fd) == ("23/02/2025", [])

    def test_impossible_date_fails(self):
        value, errors = coerce_value("31/02/2025", self.fd)
        assert value is None and errors

    def test_unnormalised_written_date_fails(self):
        value, errors = coerce_value("10 Oct, 2025", self.fd)
        assert value is None and errors

    def test_iso_format_fails_when_schema_says_dmy(self):
        value, errors = coerce_value("2025-02-23", self.fd)
        assert value is None and errors


class TestCoerceEnum:
    fd = F(type="enum", values=["male", "female", "unknown"])

    def test_member_passes(self):
        assert coerce_value("female", self.fd) == ("female", [])

    def test_case_is_normalised(self):
        assert coerce_value("Female", self.fd) == ("female", [])

    def test_whitespace_is_stripped(self):
        assert coerce_value(" male ", self.fd) == ("male", [])

    def test_non_member_fails(self):
        value, errors = coerce_value("M", self.fd)
        assert value is None and errors


class TestCoerceStringAndBool:
    def test_string_max_length(self):
        fd = F(type="string", max_length=5)
        value, errors = coerce_value("toolongvalue", fd)
        assert value is None and errors

    def test_string_regex(self):
        fd = F(type="string", regex=r"^\d{2,3}/\d{2,3}$")
        assert coerce_value("119/79", fd) == ("119/79", [])
        assert coerce_value("119 over 79", fd)[0] is None

    def test_string_is_stripped(self):
        fd = F(type="string")
        assert coerce_value("  J.D  ", fd) == ("J.D", [])

    def test_bool(self):
        fd = F(type="boolean")
        assert coerce_value(True, fd) == (True, [])
        assert coerce_value("true", fd) == (True, [])
        assert coerce_value("yes", fd)[0] is None   # not a boolean literal

    def test_checkbox_group_subset(self):
        fd = F(type="checkbox_group", values=["blood", "urine", "stool"])
        assert coerce_value(["blood", "urine"], fd) == (["blood", "urine"], [])
        assert coerce_value(["blood", "plasma"], fd)[0] is None
        assert coerce_value("blood", fd)[0] is None  # must be a list


class TestCoerceTable:
    fd = F(
        type="table",
        columns=[
            FieldDef(name="temp_c", type="float", min=25.0, max=45.0),
            FieldDef(name="pulse_bpm", type="integer", min=20, max=250),
        ],
    )

    def test_valid_rows_pass(self):
        rows = [{"temp_c": 38.2, "pulse_bpm": 104}, {"temp_c": None, "pulse_bpm": 98}]
        value, errors = coerce_value(rows, self.fd)
        assert errors == []
        assert value == rows

    def test_cell_coercion_applies(self):
        value, errors = coerce_value([{"temp_c": "38.2", "pulse_bpm": "104"}], self.fd)
        assert errors == []
        assert value == [{"temp_c": 38.2, "pulse_bpm": 104}]

    def test_bad_cell_fails_the_field(self):
        rows = [{"temp_c": 38.2, "pulse_bpm": 104}, {"temp_c": 99.9, "pulse_bpm": 98}]
        value, errors = coerce_value(rows, self.fd)
        assert value is None
        assert any("temp_c" in e for e in errors)

    def test_unknown_column_fails(self):
        value, errors = coerce_value([{"temp_c": 38.2, "spo2": 97}], self.fd)
        assert value is None and errors

    def test_missing_column_is_null_not_error(self):
        value, errors = coerce_value([{"temp_c": 38.2}], self.fd)
        assert errors == []
        assert value == [{"temp_c": 38.2, "pulse_bpm": None}]

    def test_max_rows_enforced(self):
        fd = F(type="table", max_rows=2,
               columns=[FieldDef(name="a", type="string")])
        value, errors = coerce_value([{"a": "x"}] * 3, fd)
        assert value is None and errors


# ---------------------------------------------------------------------------
# composite confidence + flagging
# ---------------------------------------------------------------------------


class TestCompositeConfidence:
    def test_valid_and_agreeing_keeps_model_confidence(self):
        c = composite_confidence(model_conf=0.9, validation_passed=True,
                                 agreement=1.0)
        assert c == pytest.approx(0.9)

    def test_validation_failure_floors_it(self):
        c = composite_confidence(model_conf=0.95, validation_passed=False,
                                 agreement=1.0)
        assert c < 0.5

    def test_disagreement_lowers_it(self):
        high = composite_confidence(0.9, True, agreement=1.0)
        low = composite_confidence(0.9, True, agreement=0.0)
        assert low < high

    def test_bounded(self):
        assert 0.0 <= composite_confidence(1.5, True, 1.0) <= 1.0
        assert 0.0 <= composite_confidence(-1, False, 0.0) <= 1.0


class TestValidateField:
    def test_clean_field_passes_unflagged(self):
        fd = F(name="age", type="integer", min=0, max=120)
        out = validate_field(
            fd, raw_value=34, legible=True, model_conf=0.95,
            raw_transcription="34", threshold=0.85,
        )
        assert isinstance(out, ValidationOutcome)
        assert out.value == 34
        assert out.validation_status == "pass"
        assert not out.flagged

    def test_the_ad_case_is_flagged(self):
        """The M0 smoke-test result: value 'Ad' for an integer field."""
        fd = F(name="age", type="integer", min=0, max=120)
        out = validate_field(fd, "Ad", True, 0.8, "Ad", 0.85)
        assert out.value is None
        assert out.validation_status == "fail"
        assert out.flagged and "coercion" in out.flag_reason

    def test_illegible_is_flagged(self):
        fd = F(name="temp", type="float")
        out = validate_field(fd, None, False, 0.3, None, 0.85)
        assert out.flagged and "illegible" in out.flag_reason

    def test_required_null_is_always_flagged(self):
        fd = F(name="doc_type", type="string", required=True)
        out = validate_field(fd, None, True, 0.99, None, 0.85)
        assert out.flagged and "required" in out.flag_reason

    def test_optional_null_legible_is_not_flagged(self):
        """A blank optional field on the form is a fact, not a problem."""
        fd = F(name="ward", type="string")
        out = validate_field(fd, None, True, 0.9, None, 0.85)
        assert not out.flagged
        assert out.validation_status == "pass"

    def test_low_confidence_is_flagged(self):
        fd = F(name="name", type="string")
        out = validate_field(fd, "J.D", True, 0.4, "J.D", 0.85)
        assert out.flagged and "confidence" in out.flag_reason

    def test_per_field_threshold_override(self):
        fd = F(name="name", type="string", review_threshold=0.5)
        out = validate_field(fd, "J.D", True, 0.6, "J.D", threshold=0.85)
        assert not out.flagged   # field says 0.5, global 0.85 must not win


# ---------------------------------------------------------------------------
# cross-field rules
# ---------------------------------------------------------------------------


class TestCrossFieldRules:
    def _run(self, rule: str, record: dict) -> list[str]:
        return evaluate_cross_field_rules(
            [CrossFieldRule(rule=rule)], record
        )

    def test_passing_rule_flags_nothing(self):
        assert self._run("a >= b", {"a": 2, "b": 1}) == []

    def test_failing_rule_flags(self):
        failed = self._run("a >= b", {"a": 1, "b": 2})
        assert failed == ["a >= b"]

    def test_none_values_do_not_crash_and_do_not_fail(self):
        # A rule over a null field is indeterminate; that is the review
        # queue's problem, not a validation failure.
        assert self._run("a >= b", {"a": None, "b": 2}) == []

    def test_len_and_boolean_operators(self):
        rec = {"document_type": "prescription", "medications": []}
        failed = self._run(
            "document_type != 'prescription' or len(medications or []) > 0", rec
        )
        assert failed  # empty meds on a prescription fails the rule

    def test_unknown_name_is_indeterminate(self):
        assert self._run("nope > 1", {"a": 1}) == []

    def test_no_arbitrary_calls(self):
        with pytest.raises(ValueError):
            self._run("__import__('os').system('rm -rf /')", {"a": 1})

    def test_no_attribute_access(self):
        with pytest.raises(ValueError):
            self._run("a.__class__", {"a": 1})
