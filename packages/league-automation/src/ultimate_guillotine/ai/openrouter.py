"""One structured-output call to OpenRouter. The only language-model boundary in the package."""
import json
from dataclasses import dataclass
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class AIUnavailable(Exception):
    """Transport failure, non-2xx status, or provider refusal. Safe to retry later."""


class AIInvalidOutput(Exception):
    """The model answered but not with JSON matching the schema."""


@dataclass(frozen=True)
class AIUsage:
    response_id: str
    prompt_tokens: int
    completion_tokens: int
    model: str


class StructuredOutputClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        http: httpx.Client,
        base_url: str = "https://openrouter.ai/api/v1",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._http = http
        self._base = base_url.rstrip("/")

    def parse(
        self,
        system: str,
        user: str,
        schema: type[T],
        schema_name: str,
    ) -> tuple[T, AIUsage]:
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": _strict_schema(schema),
                },
            },
            "provider": {"require_parameters": True},
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        last_error = "no attempt"
        for _attempt in range(2):
            try:
                response = self._http.post(
                    f"{self._base}/chat/completions",
                    json=body,
                    headers=headers,
                    timeout=60.0,
                )
            except httpx.HTTPError as exc:
                last_error = exc.__class__.__name__
                continue
            if response.status_code >= 500:
                last_error = f"status {response.status_code}"
                continue
            if response.status_code != 200:
                raise AIUnavailable(
                    f"openrouter returned status {response.status_code}"
                )
            return _parse_response(response.json(), schema)
        raise AIUnavailable(f"openrouter unavailable after retry: {last_error}")


def _strict_schema(schema: type[BaseModel]) -> dict:
    """Pydantic JSON schema with additionalProperties=false on every object,
    as strict mode requires."""
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


def _parse_response(payload: dict, schema: type[T]) -> tuple[T, AIUsage]:  # noqa: UP047
    try:
        content = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage") or {}
        meta = AIUsage(
            response_id=str(payload.get("id", "")),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            model=str(payload.get("model", "")),
        )
    except (KeyError, IndexError, TypeError) as exc:
        raise AIInvalidOutput(
            f"unexpected response shape: {exc.__class__.__name__}"
        ) from exc
    try:
        return schema.model_validate(json.loads(content)), meta
    except (json.JSONDecodeError, ValidationError) as exc:
        raise AIInvalidOutput(
            f"model output did not match schema: {exc.__class__.__name__}"
        ) from exc
