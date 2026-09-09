import json

import httpx
import pytest
import respx
from pydantic import BaseModel

from ultimate_guillotine.ai.openrouter import AIInvalidOutput, AIUnavailable, StructuredOutputClient

URL = "https://openrouter.ai/api/v1/chat/completions"


class Shape(BaseModel):
    name: str
    sides: int


def ok(content: str) -> httpx.Response:
    return httpx.Response(200, json={
        "id": "gen-1", "model": "openai/gpt-5-mini",
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7},
    })


@respx.mock
def test_parse_sends_schema_and_returns_model_and_usage() -> None:
    route = respx.post(URL).mock(return_value=ok(json.dumps({"name": "square", "sides": 4})))
    client = StructuredOutputClient("key", "openai/gpt-5-mini", httpx.Client())
    shape, usage = client.parse("sys", "user text", Shape, "shape")
    assert shape == Shape(name="square", sides=4)
    assert usage.response_id == "gen-1" and usage.prompt_tokens == 12 and usage.completion_tokens == 7
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "openai/gpt-5-mini"
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["messages"][1] == {"role": "user", "content": "user text"}
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "shape"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert body["provider"] == {"require_parameters": True}
    assert route.calls.last.request.headers["authorization"] == "Bearer key"


@respx.mock
def test_parse_retries_once_on_server_error_then_raises_unavailable() -> None:
    route = respx.post(URL).mock(side_effect=[httpx.Response(503), httpx.Response(503)])
    client = StructuredOutputClient("key", "m", httpx.Client())
    with pytest.raises(AIUnavailable):
        client.parse("s", "u", Shape, "shape")
    assert route.call_count == 2


@respx.mock
def test_parse_raises_invalid_output_when_json_does_not_match_schema() -> None:
    respx.post(URL).mock(return_value=ok(json.dumps({"name": "circle"})))
    client = StructuredOutputClient("key", "m", httpx.Client())
    with pytest.raises(AIInvalidOutput):
        client.parse("s", "u", Shape, "shape")


@respx.mock
def test_error_messages_never_include_the_key() -> None:
    respx.post(URL).mock(return_value=httpx.Response(401, json={"error": "bad key"}))
    client = StructuredOutputClient("sk-secret-value", "m", httpx.Client())
    with pytest.raises(AIUnavailable) as info:
        client.parse("s", "u", Shape, "shape")
    assert "sk-secret-value" not in str(info.value)
