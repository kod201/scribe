"""JSON-repair path tests (PRD 7.2), written before the implementation.

The contract: parse strict JSON; on failure apply deterministic repairs; the
one model-retry lives in the extract stage, not here. Anything unparseable
after repair returns None and the field flags as 'unparsed'.
"""

from __future__ import annotations

from scribe.stages.jsonrepair import parse_model_json


class TestCleanJson:
    def test_plain_object(self):
        assert parse_model_json('{"value": 34, "legible": true}') == {
            "value": 34, "legible": True,
        }

    def test_whitespace_padding(self):
        assert parse_model_json('  \n {"value": null} \n ') == {"value": None}


class TestCommonModelArtifacts:
    def test_markdown_fence(self):
        text = '```json\n{"value": "J.D", "legible": true}\n```'
        assert parse_model_json(text) == {"value": "J.D", "legible": True}

    def test_fence_without_language(self):
        assert parse_model_json('```\n{"value": 1}\n```') == {"value": 1}

    def test_leading_prose(self):
        text = 'Here is the extracted field:\n{"value": "F.O", "legible": true}'
        assert parse_model_json(text) == {"value": "F.O", "legible": True}

    def test_trailing_prose(self):
        text = '{"value": 12}\nLet me know if you need anything else.'
        assert parse_model_json(text) == {"value": 12}

    def test_nested_objects_are_not_truncated(self):
        text = 'Result: {"value": {"a": {"b": 1}}, "legible": true} done'
        assert parse_model_json(text) == {"value": {"a": {"b": 1}}, "legible": True}

    def test_braces_inside_strings_do_not_confuse_extraction(self):
        text = '{"value": "dose {unclear}", "legible": false}'
        assert parse_model_json(text) == {"value": "dose {unclear}", "legible": False}

    def test_trailing_comma(self):
        assert parse_model_json('{"value": 1, "legible": true,}') == {
            "value": 1, "legible": True,
        }

    def test_trailing_comma_in_array(self):
        assert parse_model_json('{"value": [1, 2,]}') == {"value": [1, 2]}

    def test_thinking_block_before_json(self):
        text = "<think>The age box says 34.</think>\n{\"value\": 34}"
        assert parse_model_json(text) == {"value": 34}


class TestUnrepairable:
    def test_empty_string(self):
        assert parse_model_json("") is None

    def test_prose_only(self):
        assert parse_model_json("The value is thirty-four.") is None

    def test_truncated_json(self):
        assert parse_model_json('{"value": "unterminated') is None

    def test_top_level_array_is_rejected(self):
        # The contract is an object envelope; a bare array is a wrong shape.
        assert parse_model_json('[1, 2, 3]') is None

    def test_python_literals_are_not_json(self):
        assert parse_model_json("{'value': None}") is None
