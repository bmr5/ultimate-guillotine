import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from ultimate_guillotine.messages.bluebubbles import (
    BlueBubblesClient,
    BlueBubblesError,
    parse_webhook,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "bluebubbles" / "new_message.json"


def test_parse_webhook_new_message() -> None:
    msg = parse_webhook(json.loads(FIXTURE.read_text()))
    assert msg.chat_guid == "iMessage;+;chat-test"
    assert msg.sender_address == "+15555550100"
    assert msg.is_group is True
    assert msg.sent_at.tzinfo is UTC


def test_parse_webhook_ignores_other_events() -> None:
    assert parse_webhook({"type": "typing-indicator", "data": {}}) is None


@respx.mock
def test_send_text_posts_chat_guid_and_returns_guid() -> None:
    route = respx.post("http://bb.local/api/v1/message/text").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": {"guid": "sent-1"}})
    )
    client = BlueBubblesClient("http://bb.local", "pw", httpx.Client())
    assert client.send_text("iMessage;+;chat-test", "hi") == "sent-1"
    body = json.loads(route.calls.last.request.content)
    assert body["chatGuid"] == "iMessage;+;chat-test"
    assert body["message"] == "hi"
    assert "tempGuid" in body
    assert "method" not in body
    assert route.calls.last.request.url.params["password"] == "pw"


@respx.mock
def test_send_text_raises_on_error() -> None:
    respx.post("http://bb.local/api/v1/message/text").mock(return_value=httpx.Response(500, json={"status": 500, "message": "boom"}))
    client = BlueBubblesClient("http://bb.local", "pw", httpx.Client())
    with pytest.raises(BlueBubblesError):
        client.send_text("iMessage;+;chat-test", "hi")


@respx.mock
def test_messages_after_uses_ms_and_parses() -> None:
    route = respx.get("http://bb.local/api/v1/chat/iMessage%3B%2B%3Bchat-test/message").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": [json.loads(FIXTURE.read_text())["data"]]})
    )
    client = BlueBubblesClient("http://bb.local", "pw", httpx.Client())
    out = client.messages_after("iMessage;+;chat-test", datetime(2026, 9, 8, tzinfo=UTC))
    assert route.calls.last.request.url.params["after"] == "1788825600000"
    assert route.calls.last.request.url.params["sort"] == "ASC"
    assert out[0].guid == "p:0/ABC"


@respx.mock
def test_ensure_webhook_creates_when_missing() -> None:
    respx.get("http://bb.local/api/v1/webhook").mock(return_value=httpx.Response(200, json={"status": 200, "data": []}))
    create = respx.post("http://bb.local/api/v1/webhook").mock(return_value=httpx.Response(200, json={"status": 200, "data": {"id": 1}}))
    BlueBubblesClient("http://bb.local", "pw", httpx.Client()).ensure_webhook("http://127.0.0.1:8646/bluebubbles-webhook?password=x")
    assert json.loads(create.calls.last.request.content)["events"] == ["new-message"]
