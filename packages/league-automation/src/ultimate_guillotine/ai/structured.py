"""The structured-output boundary: the one contract every language-model call obeys.

Transport lives in the backend modules next door. What stays here is the part no
backend gets to reinterpret -- the two failure kinds, the usage record, the client
protocol, and the schema/text handling both sides of a call need.
"""

import json
from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class AIUnavailable(Exception):
    """The model could not be reached, or refused. Safe to retry later."""


class AIInvalidOutput(Exception):
    """The model answered but not with JSON matching the schema."""


@dataclass(frozen=True)
class AIUsage:
    response_id: str
    prompt_tokens: int
    completion_tokens: int
    model: str


class StructuredOutputClient(Protocol):
    """One structured call: a system prompt, a user message, and a schema to fill."""

    def parse(
        self,
        system: str,
        user: str,
        schema: type[T],
        schema_name: str,
    ) -> tuple[T, AIUsage]: ...


def strict_schema(schema: type[BaseModel]) -> dict:
    """Pydantic JSON schema with additionalProperties=false on every object and
    every property required, as strict structured-output modes ask for."""
    raw = schema.model_json_schema()

    def harden(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}).keys())
            for value in node.values():
                harden(value)
        elif isinstance(node, list):
            for item in node:
                harden(item)

    harden(raw)
    return raw


def parse_model_text(text: str, schema: type[T]) -> T:  # noqa: UP047
    """Validate `text` against `schema`, tolerating the wrapping a chat model adds.

    A CLI backend answers in prose-shaped text, not a JSON envelope: code fences
    and a sentence either side of the object are normal even when the prompt asks
    for neither. Everything outside the outermost braces is dropped.

    Raises `AIInvalidOutput` naming only the exception class. The rejected text is
    a league chat message, so it never reaches the message -- the original
    exception is chained for a caller that needs the detail.
    """
    try:
        return schema.model_validate(json.loads(_json_block(text)))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise AIInvalidOutput(
            f"model output did not match schema: {exc.__class__.__name__}"
        ) from exc


def _json_block(text: str) -> str:
    body = text.strip()
    if "```" in body:
        fenced = body.split("```")
        if len(fenced) >= 3:
            block = fenced[1]
            newline = block.find("\n")
            if newline != -1 and block[:newline].strip().lower() in {"", "json"}:
                block = block[newline + 1 :]
            body = block.strip()
    start, end = body.find("{"), body.rfind("}")
    if start != -1 and end > start:
        return body[start : end + 1]
    return body
