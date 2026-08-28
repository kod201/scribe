"""Stage 4: validate (PRD 5.1, 7.3).

Type coercion, constraint checks, cross-field rules, composite confidence,
and the flagging decision. Coercion is deliberately unforgiving: it never
strips units, never reinterprets, never guesses. Normalising is the model's
job; proving the normalisation happened is this stage's job. Anything that
fails lands in the review queue with the raw transcription intact.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from scribe.schema import CrossFieldRule, FieldDef

# ---------------------------------------------------------------------------
# coercion
# ---------------------------------------------------------------------------


def coerce_value(value: Any, fd: FieldDef) -> tuple[Any, list[str]]:
    """Coerce `value` to the field's type. Returns (coerced, errors).

    On any failure the coerced value is None and errors say why -- the raw
    model output is preserved elsewhere (extractions.value stores the coerced
    form, raw_transcription the faithful one).
    """
    if value is None:
        return None, []
    try:
        return _coerce(value, fd), []
    except _CoercionError as e:
        return None, [str(e)]


class _CoercionError(ValueError):
    pass


def _fail(fd: FieldDef, msg: str) -> None:
    raise _CoercionError(f"{fd.name}: coercion failed -- {msg}")


def _coerce(value: Any, fd: FieldDef) -> Any:
    t = fd.type
    if t == "integer":
        return _coerce_int(value, fd)
    if t == "float":
        return _coerce_float(value, fd)
    if t in ("date", "datetime"):
        return _coerce_date(value, fd)
    if t == "enum":
        return _coerce_enum(value, fd)
    if t == "boolean":
        return _coerce_bool(value, fd)
    if t == "checkbox_group":
        return _coerce_checkbox_group(value, fd)
    if t == "table":
        return _coerce_table(value, fd)
    if t in ("string", "free_text"):
        return _coerce_string(value, fd)
    _fail(fd, f"unknown field type {t!r}")


def _check_range(n: float, fd: FieldDef) -> None:
    if fd.min is not None and n < fd.min:
        _fail(fd, f"{n} is below min {fd.min}")
    if fd.max is not None and n > fd.max:
        _fail(fd, f"{n} is above max {fd.max}")


def _coerce_int(value: Any, fd: FieldDef) -> int:
    if isinstance(value, bool):
        _fail(fd, "boolean is not an integer")
    if isinstance(value, int):
        n = value
    elif isinstance(value, float):
        if not value.is_integer():
            _fail(fd, f"{value} has a fractional part")
        n = int(value)
    elif isinstance(value, str):
        s = value.strip()
        if not re.fullmatch(r"[+-]?\d+", s):
            _fail(fd, f"{value!r} is not an integer")
        n = int(s)
    else:
        _fail(fd, f"cannot coerce {type(value).__name__} to integer")
    _check_range(n, fd)
    return n


def _coerce_float(value: Any, fd: FieldDef) -> float:
    if isinstance(value, bool):
        _fail(fd, "boolean is not a number")
    if isinstance(value, (int, float)):
        n = float(value)
    elif isinstance(value, str):
        s = value.strip()
        if not re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)", s):
            _fail(fd, f"{value!r} is not a number")
        n = float(s)
    else:
        _fail(fd, f"cannot coerce {type(value).__name__} to float")
    _check_range(n, fd)
    return n


def _coerce_date(value: Any, fd: FieldDef) -> str:
    if not isinstance(value, str):
        _fail(fd, f"date must be a string, got {type(value).__name__}")
    s = value.strip()
    fmt = fd.format or "%d/%m/%Y"
    try:
        datetime.strptime(s, fmt)
    except ValueError:
        _fail(fd, f"{value!r} does not parse as {fmt}")
    return s


def _coerce_enum(value: Any, fd: FieldDef) -> str:
    if not isinstance(value, str):
        _fail(fd, f"enum value must be a string, got {type(value).__name__}")
    s = value.strip().lower()
    members = {m.lower(): m for m in (fd.values or [])}
    if s not in members:
        _fail(fd, f"{value!r} is not one of {fd.values}")
    return members[s]


def _coerce_bool(value: Any, fd: FieldDef) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    _fail(fd, f"{value!r} is not a boolean")


def _coerce_checkbox_group(value: Any, fd: FieldDef) -> list[str]:
    if not isinstance(value, list):
        _fail(fd, "checkbox_group must be a list")
    members = {m.lower(): m for m in (fd.values or [])}
    out = []
    for item in value:
        if not isinstance(item, str) or item.strip().lower() not in members:
            _fail(fd, f"{item!r} is not one of {fd.values}")
        out.append(members[item.strip().lower()])
    return out


def _coerce_string(value: Any, fd: FieldDef) -> str:
    if not isinstance(value, str):
        _fail(fd, f"expected a string, got {type(value).__name__}")
    s = value.strip()
    if fd.max_length and len(s) > fd.max_length:
        _fail(fd, f"length {len(s)} exceeds max_length {fd.max_length}")
    if fd.regex and not re.fullmatch(fd.regex, s):
        _fail(fd, f"{s!r} does not match {fd.regex}")
    return s


def _coerce_table(value: Any, fd: FieldDef) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        _fail(fd, "table must be a list of row objects")
    if len(value) > fd.max_rows:
        _fail(fd, f"{len(value)} rows exceeds max_rows {fd.max_rows}")
    cols = {c.name: c for c in fd.columns or []}
    out: list[dict[str, Any]] = []
    for i, row in enumerate(value):
        if not isinstance(row, dict):
            _fail(fd, f"row {i} is not an object")
        unknown = set(row) - set(cols)
        if unknown:
            _fail(fd, f"row {i} has unknown columns {sorted(unknown)}")
        coerced_row: dict[str, Any] = {}
        for name, cfd in cols.items():
            cell = row.get(name)
            if cell is None:
                coerced_row[name] = None
                continue
            try:
                coerced_row[name] = _coerce(cell, cfd)
            except _CoercionError as e:
                _fail(fd, f"row {i}: {e}")
        out.append(coerced_row)
    return out


# ---------------------------------------------------------------------------
# composite confidence (PRD 7.3)
# ---------------------------------------------------------------------------

# Documented formula: start from the model's self-reported confidence, scale by
# agreement between value and raw_transcription (parse/consistency evidence),
# and floor hard on validation failure. Weights are deliberately simple; M4
# tunes them against the held-out set.
_AGREEMENT_FLOOR = 0.6      # agreement scales composite within [floor, 1.0]
_VALIDATION_FAIL_FACTOR = 0.2


def composite_confidence(
    model_conf: float, validation_passed: bool, agreement: float
) -> float:
    c = min(max(model_conf, 0.0), 1.0)
    a = min(max(agreement, 0.0), 1.0)
    c *= _AGREEMENT_FLOOR + (1.0 - _AGREEMENT_FLOOR) * a
    if not validation_passed:
        c *= _VALIDATION_FAIL_FACTOR
    return min(max(c, 0.0), 1.0)


def value_raw_agreement(fd: FieldDef, value: Any, raw: str | None) -> float:
    """Cheap consistency evidence between the interpreted value and what was
    written. 1.0 = consistent or not applicable, 0.0 = contradictory."""
    if value is None or raw is None:
        return 0.5 if value is not None else 1.0
    raw_s = str(raw).strip()
    if fd.type == "integer":
        digits = re.findall(r"\d+", raw_s)
        return 1.0 if str(value) in digits else 0.0
    if fd.type == "float":
        nums = re.findall(r"\d+(?:\.\d+)?", raw_s)
        return 1.0 if any(abs(float(n) - value) < 1e-9 for n in nums) else 0.0
    if fd.type == "date":
        # The written form rarely matches the normalised one; require the day
        # or year to appear somewhere in the raw text as weak evidence.
        parts = re.findall(r"\d+", raw_s)
        try:
            dt = datetime.strptime(value, fd.format or "%d/%m/%Y")
        except ValueError:
            return 0.0
        evid = {str(dt.day), f"{dt.day:02d}", str(dt.year), str(dt.year % 100)}
        return 1.0 if evid & set(parts) else 0.0
    return 1.0


# ---------------------------------------------------------------------------
# per-field validation outcome
# ---------------------------------------------------------------------------


@dataclass
class ValidationOutcome:
    value: Any
    validation_status: str            # pass | fail
    validation_errors: list[str] = field(default_factory=list)
    composite: float = 0.0
    flagged: bool = False
    flag_reason: str | None = None


def validate_field(
    fd: FieldDef,
    raw_value: Any,
    legible: bool,
    model_conf: float,
    raw_transcription: str | None,
    threshold: float,
) -> ValidationOutcome:
    value, errors = coerce_value(raw_value, fd)
    passed = not errors
    agreement = value_raw_agreement(fd, value, raw_transcription)
    composite = composite_confidence(model_conf, passed, agreement)

    reasons: list[str] = []
    if errors:
        reasons.append("coercion/validation failed")
    if not legible:
        reasons.append("model reports illegible")
    if fd.required and value is None:
        reasons.append("required field is null")
    if value is not None and composite < fd.threshold(threshold):
        reasons.append(
            f"composite confidence {composite:.2f} below "
            f"threshold {fd.threshold(threshold):.2f}"
        )

    return ValidationOutcome(
        value=value,
        validation_status="pass" if passed else "fail",
        validation_errors=errors,
        composite=composite,
        flagged=bool(reasons),
        flag_reason="; ".join(reasons) if reasons else None,
    )


# ---------------------------------------------------------------------------
# cross-field rules (PRD 6)
# ---------------------------------------------------------------------------

_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Is, ast.IsNot, ast.In, ast.NotIn,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.Name, ast.Load, ast.Constant, ast.List, ast.Tuple, ast.Call,
    ast.IfExp,
)
_ALLOWED_CALLS = {"len"}


class _Indeterminate(Exception):
    """Rule touches a null or missing field; treat as not-failed."""


def _safe_eval(node: ast.AST, names: dict[str, Any]) -> Any:
    if not isinstance(node, _ALLOWED_NODES):
        raise ValueError(
            f"cross_field_rule uses disallowed syntax: {type(node).__name__}"
        )
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body, names)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_safe_eval(e, names) for e in node.elts]
    if isinstance(node, ast.Name):
        if node.id not in names:
            raise _Indeterminate(node.id)
        return names[node.id]
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_CALLS:
            raise ValueError("cross_field_rule may only call len()")
        args = [_safe_eval(a, names) for a in node.args]
        return len(*args)
    if isinstance(node, ast.BoolOp):
        vals = [_safe_eval(v, names) for v in node.values]
        if isinstance(node.op, ast.And):
            out = vals[0]
            for v in vals[1:]:
                out = out and v
            return out
        out = vals[0]
        for v in vals[1:]:
            out = out or v
        return out
    if isinstance(node, ast.UnaryOp):
        return not _safe_eval(node.operand, names)
    if isinstance(node, ast.IfExp):
        return (_safe_eval(node.body, names)
                if _safe_eval(node.test, names)
                else _safe_eval(node.orelse, names))
    if isinstance(node, ast.BinOp):
        left, right = _safe_eval(node.left, names), _safe_eval(node.right, names)
        if left is None or right is None:
            raise _Indeterminate("null operand")
        ops = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
               ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}
        return ops[type(node.op)](left, right)
    if isinstance(node, ast.Compare):
        left = _safe_eval(node.left, names)
        for op, comparator in zip(node.ops, node.comparators):
            right = _safe_eval(comparator, names)
            if isinstance(op, (ast.Is, ast.IsNot)):
                ok = (left is right) if isinstance(op, ast.Is) else (left is not right)
            elif isinstance(op, (ast.Eq, ast.NotEq)):
                ok = (left == right) if isinstance(op, ast.Eq) else (left != right)
            elif isinstance(op, (ast.In, ast.NotIn)):
                if right is None:
                    raise _Indeterminate("null container")
                ok = (left in right) if isinstance(op, ast.In) else (left not in right)
            else:
                if left is None or right is None:
                    raise _Indeterminate("null comparison")
                ok = {ast.Lt: left < right, ast.LtE: left <= right,
                      ast.Gt: left > right, ast.GtE: left >= right}[type(op)]
            if not ok:
                return False
            left = right
        return True
    raise ValueError(f"unhandled node {type(node).__name__}")


def evaluate_cross_field_rules(
    rules: list[CrossFieldRule], record: dict[str, Any]
) -> list[str]:
    """Returns the rule expressions that FAILED. Rules touching null/missing
    fields are indeterminate and do not fail -- the nulls are already flagged
    by per-field validation."""
    failed: list[str] = []
    for rule in rules:
        tree = ast.parse(rule.rule, mode="eval")
        try:
            ok = _safe_eval(tree, dict(record))
        except _Indeterminate:
            continue
        if not ok:
            failed.append(rule.rule)
    return failed
