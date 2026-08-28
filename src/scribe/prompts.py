"""Prompt construction for field extraction (PRD 7.1, 7.2).

PROMPT_VERSION participates in the extractions unique key, so changing any
wording here and re-running produces new rows instead of silently mixing
outputs from different prompts.
"""

from __future__ import annotations

import json
from typing import Any

from scribe.schema import FieldDef, Schema

PROMPT_VERSION = "v2"

SYSTEM_PROMPT = """\
You read a single field from a scanned clinical form and output only JSON.

Rules you must follow exactly:
- Output a single JSON object and nothing else. No prose, no markdown fences.
- raw_transcription is EXACTLY what is written on the page, uninterpreted, \
character by character as best you can read it. value is your interpretation \
of it in the required format. These are different jobs; never let the \
interpretation leak into raw_transcription.
- Never guess. If fewer than about 70% of the strokes are readable, set \
legible=false and value=null. A wrong value is far worse than a null.
- If the field is simply not present or not filled in on this page, set \
value=null, legible=true, and say so in note.
- If something is ambiguous, struck through, or overwritten, extract your \
best reading only if you are confident, and describe the issue in note.
- confidence is your honest estimate in [0,1] that value is exactly correct. \
Do not inflate it. Calibration rule: if ANY character of the value could \
plausibly be read another way, confidence must be 0.7 or lower. Reserve \
values above 0.9 for text you could defend stroke by stroke.
- Transcribe names and identifiers letter by letter as strokes, not as words \
you expect. Unusual spellings are normal in this data; NEVER normalise a \
name toward a more common one. If a letter is ambiguous, pick the likeliest \
stroke reading and lower confidence.
"""

REPAIR_PROMPT = """\
Your previous reply was not valid JSON and could not be parsed.

Reply again with ONLY the JSON object -- no explanation, no markdown fences, \
no text before or after it. The required shape is:

{shape}
"""


# -- envelope shapes ---------------------------------------------------------


def _scalar_value_schema(fd: FieldDef) -> dict[str, Any]:
    if fd.type == "integer":
        return {"type": ["integer", "null"]}
    if fd.type == "float":
        return {"type": ["number", "null"]}
    if fd.type == "boolean":
        return {"type": ["boolean", "null"]}
    if fd.type == "enum":
        return {"enum": list(fd.values or []) + [None]}
    if fd.type == "checkbox_group":
        return {
            "type": ["array", "null"],
            "items": {"enum": list(fd.values or [])},
        }
    # string / free_text / date / datetime travel as strings
    return {"type": ["string", "null"]}


def value_schema(fd: FieldDef) -> dict[str, Any]:
    if fd.type != "table":
        return _scalar_value_schema(fd)
    row_props = {c.name: _scalar_value_schema(c) for c in fd.columns or []}
    return {
        "type": ["array", "null"],
        "items": {
            "type": "object",
            "properties": row_props,
            "required": list(row_props),
            "additionalProperties": False,
        },
        "maxItems": fd.max_rows,
    }


def envelope_schema(fd: FieldDef) -> dict[str, Any]:
    """JSON Schema for the PRD 7.2 output shape, used both for constrained
    decoding and for documentation inside the prompt."""
    return {
        "type": "object",
        "properties": {
            "value": value_schema(fd),
            "legible": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "raw_transcription": {"type": ["string", "null"]},
            "note": {"type": ["string", "null"]},
        },
        "required": ["value", "legible", "confidence", "raw_transcription", "note"],
        "additionalProperties": False,
    }


# -- user prompt --------------------------------------------------------------


def _constraint_lines(fd: FieldDef) -> list[str]:
    lines: list[str] = []
    if fd.type == "integer" or fd.type == "float":
        if fd.min is not None or fd.max is not None:
            lines.append(f"- Plausible range: {fd.min} to {fd.max}.")
    if fd.type in ("date", "datetime"):
        lines.append(f"- value must be formatted exactly as {fd.format or '%d/%m/%Y'}"
                     f" (strftime notation).")
    if fd.type == "enum":
        lines.append(f"- value must be exactly one of: {', '.join(fd.values or [])},"
                     f" or null.")
    if fd.type == "checkbox_group":
        lines.append(f"- value is a JSON array containing only items that are"
                     f" actually marked, from: {', '.join(fd.values or [])}.")
    if fd.max_length:
        lines.append(f"- Maximum length {fd.max_length} characters.")
    if fd.regex:
        lines.append(f"- value must match the regular expression {fd.regex}")
    return lines


def _table_lines(fd: FieldDef) -> list[str]:
    lines = ["- value is a JSON array with one object per row, in reading order.",
             "- Every row object must contain every column key; use null for a"
             " cell that is empty or unreadable.",
             "- Columns:"]
    for c in fd.columns or []:
        desc = c.extract_hint or ""
        rng = ""
        if c.min is not None or c.max is not None:
            rng = f" (range {c.min}..{c.max})"
        fmt = f" (format {c.format})" if c.format else ""
        lines.append(f"    - {c.name} ({c.type}{rng}{fmt}): {desc}")
    return lines


def field_user_prompt(fd: FieldDef, schema: Schema) -> str:
    parts = [
        f"Schema: {schema.schema_id} v{schema.version}.",
        f"Field to extract: {fd.name} (type: {fd.type}).",
    ]
    if fd.locate_hint:
        parts.append(f"Where to look: {fd.locate_hint}")
    if fd.extract_hint:
        parts.append(f"How to read it: {fd.extract_hint}")
    lines = _table_lines(fd) if fd.type == "table" else _constraint_lines(fd)
    if lines:
        parts.append("Constraints:\n" + "\n".join(lines))
    parts.append(
        "Reply with only a JSON object of this exact shape:\n"
        + json.dumps(envelope_schema(fd), indent=2)
    )
    return "\n\n".join(parts)


def repair_user_prompt(fd: FieldDef) -> str:
    return REPAIR_PROMPT.format(shape=json.dumps(envelope_schema(fd), indent=2))
