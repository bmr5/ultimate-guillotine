"""The transport-free half of the model boundary: schema hardening and text parsing."""

import json

import pytest
from pydantic import BaseModel

from ultimate_guillotine.ai.structured import AIInvalidOutput, parse_model_text, strict_schema


class Shape(BaseModel):
    name: str
    sides: int


def test_strict_schema_closes_every_object_and_requires_every_property() -> None:
    schema = strict_schema(Shape)
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == ["name", "sides"]


def test_parse_model_text_reads_a_bare_json_object() -> None:
    assert parse_model_text(json.dumps({"name": "square", "sides": 4}), Shape) == Shape(
        name="square", sides=4
    )


def test_parse_model_text_strips_code_fences() -> None:
    text = '```json\n{"name": "square", "sides": 4}\n```'
    assert parse_model_text(text, Shape) == Shape(name="square", sides=4)


def test_parse_model_text_strips_leading_and_trailing_prose() -> None:
    text = 'Sure, here is the JSON:\n{"name": "square", "sides": 4}\nLet me know if that helps.'
    assert parse_model_text(text, Shape) == Shape(name="square", sides=4)


def test_parse_model_text_raises_invalid_output_on_a_schema_mismatch() -> None:
    with pytest.raises(AIInvalidOutput) as info:
        parse_model_text(json.dumps({"name": "circle"}), Shape)
    assert "ValidationError" in str(info.value)


def test_parse_model_text_raises_invalid_output_on_prose_only() -> None:
    with pytest.raises(AIInvalidOutput):
        parse_model_text("I could not work that one out, sorry.", Shape)


def test_parse_model_text_reports_only_the_exception_class_name() -> None:
    """The rejected text is the league's chat message: it must not reach a log line."""
    with pytest.raises(AIInvalidOutput) as info:
        parse_model_text('{"name": "Member01 trades Player Alpha", "sides": "many"}', Shape)
    assert "Member01" not in str(info.value)
