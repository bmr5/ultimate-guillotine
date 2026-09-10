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
    respx.post("http://bb.local/api/v1/message/text").mock(
        return_value=httpx.Response(500, json={"status": 500, "message": "boom"})
    )
    client = BlueBubblesClient("http://bb.local", "pw", httpx.Client())
    with pytest.raises(BlueBubblesError):
        client.send_text("iMessage;+;chat-test", "hi")


@respx.mock
def test_messages_after_uses_ms_and_parses() -> None:
    route = respx.get("http://bb.local/api/v1/chat/iMessage%3B%2B%3Bchat-test/message").mock(
        return_value=httpx.Response(
            200, json={"status": 200, "data": [json.loads(FIXTURE.read_text())["data"]]}
        )
    )
    client = BlueBubblesClient("http://bb.local", "pw", httpx.Client())
    out = client.messages_after("iMessage;+;chat-test", datetime(2026, 9, 8, tzinfo=UTC))
    assert route.calls.last.request.url.params["after"] == "1788825600000"
    assert route.calls.last.request.url.params["sort"] == "ASC"
    assert out[0].guid == "p:0/ABC"


@respx.mock
def test_ensure_webhook_creates_when_missing() -> None:
    respx.get("http://bb.local/api/v1/webhook").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": []})
    )
    create = respx.post("http://bb.local/api/v1/webhook").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": {"id": 1}})
    )
    BlueBubblesClient("http://bb.local", "pw", httpx.Client()).ensure_webhook(
        "http://127.0.0.1:8646/bluebubbles-webhook?password=x"
    )
    assert json.loads(create.calls.last.request.content)["events"] == ["new-message"]


def test_a_tapback_is_not_a_message() -> None:
    """A reaction quotes the whole alert it reacts to, so it read as a repost of
    the alert until the listener learned to drop it (Ben's chat, 2026-09-10)."""
    original = {
        "type": "new-message",
        "data": {
            "guid": "m1",
            "chatGuid": "iMessage;+;chat1",
            "text": "🚨 Trade alert 🚨 a sends b to c for 10",
            "isFromMe": False,
            "dateCreated": 1757000000000,
            "handle": {"address": "+15555550100"},
        },
    }
    assert parse_webhook(original) is not None
    for kind in ("like", 2000, 2006, "3001"):
        reaction = {
            "type": "new-message",
            "data": {
                **original["data"],
                "guid": f"r-{kind}",
                "text": "Liked “🚨 Trade alert 🚨 a sends b to c for 10”",
                "associatedMessageGuid": "p:0/m1",
                "associatedMessageType": kind,
            },
        }
        assert parse_webhook(reaction) is None, kind
    plain = {"type": "new-message", "data": {**original["data"], "associatedMessageType": 0}}
    assert parse_webhook(plain) is not None


def test_parse_webhook_reads_the_reply_thread_and_attachment_names() -> None:
    record = json.loads(FIXTURE.read_text())
    record["data"]["threadOriginatorGuid"] = "p:0/BOT-1"
    record["data"]["attachments"] = [{"guid": "a1", "transferName": "bowers-hold-week-6.html"}]
    msg = parse_webhook(record)
    assert msg.thread_originator_guid == "p:0/BOT-1"
    assert msg.attachment_names == ("bowers-hold-week-6.html",)


def test_parse_webhook_falls_back_to_reply_to_guid() -> None:
    record = json.loads(FIXTURE.read_text())
    record["data"]["replyToGuid"] = "p:0/BOT-2"
    assert parse_webhook(record).thread_originator_guid == "p:0/BOT-2"


def test_a_plain_message_has_no_thread_and_no_attachments() -> None:
    msg = parse_webhook(json.loads(FIXTURE.read_text()))
    assert msg.thread_originator_guid is None
    assert msg.attachment_names == ()
