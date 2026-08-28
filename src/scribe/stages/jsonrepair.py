"""Deterministic JSON repair for model output (PRD 7.2).

Strict parse first; then a small set of mechanical fixes for the artifacts
VLMs actually produce (fences, prose around the object, trailing commas,
think-blocks). No creative repair: if the object is genuinely malformed the
caller gets None and the field is flagged 'unparsed'. The one permitted
model-retry with a repair prompt lives in the extract stage.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:[a-zA-Z0-9_-]+)?\s*\n?(.*?)```", re.DOTALL)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def parse_model_json(text: str) -> dict[str, Any] | None:
    """Parse model output into the field envelope. None if unrecoverable."""
    if not text or not text.strip():
        return None

    candidates = [text]

    stripped = _THINK_RE.sub("", text)
    if stripped != text:
        candidates.append(stripped)

    for source in list(candidates):
        for m in _FENCE_RE.finditer(source):
            candidates.append(m.group(1))

    for source in list(candidates):
        block = _first_balanced_object(source)
        if block and block not in candidates:
            candidates.append(block)

    for source in list(candidates):
        fixed = _TRAILING_COMMA_RE.sub(r"\1", source)
        if fixed not in candidates:
            candidates.append(fixed)

    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _first_balanced_object(text: str) -> str | None:
    """Extract the first balanced {...} block, respecting string literals."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None
