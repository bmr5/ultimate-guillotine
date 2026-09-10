from datetime import UTC, datetime

import pytest

from ultimate_guillotine.config import DeliveryMode, Settings
from ultimate_guillotine.core.signature import sign
from ultimate_guillotine.data.repositories import DeliveryTarget, OutboundRecord
from ultimate_guillotine.messages.bluebubbles import InboundMessage
from ultimate_guillotine.messages.delivery import (
    DeliveryDisabled,
    DeliveryService,
    TargetMismatch,
    content_hash,
)
from ultimate_guillotine.messages.fingerprint import participant_fingerprint

TEST_GUID = "iMessage;+;chat-test"
PROD_GUID = "iMessage;+;chat-prod"
PROD_MEMBERS = ["+15555550100", "+15555550101"]


class FakeClient:
    def __init__(self) -> None:
        self.sent = []
        self.participants = {PROD_GUID: PROD_MEMBERS, TEST_GUID: ["+15555550100"]}
        self.history = []

    def chat_participants(self, chat_guid):
        return self.participants[chat_guid]

    def send_text(self, chat_guid, text):
        self.sent.append((chat_guid, text))
        return f"guid-{len(self.sent)}"

    def send_attachment(self, chat_guid, filename, data, mime="text/html"):
        self.sent.append((chat_guid, filename, data))
        return f"guid-{len(self.sent)}"

    def messages_after(self, chat_guid, after, limit=100):
        return self.history


class FakeTargets:
    def __init__(self, rows):
        self.rows = rows

    def get(self, mode):
        return self.rows.get(mode)


class FakeOutbound:
    def __init__(self) -> None:
        self.records = {}
        self.pending = None

    def reserve(self, run_id, target_id, content, hash_):
        oid = len(self.records) + 1
        self.records[oid] = {"state": "reserved", "hash": hash_}
        return oid

    def set_state(self, oid, state, bluebubbles_guid=None, error=None):
        self.records[oid]["state"] = state
        self.records[oid]["guid"] = bluebubbles_guid

    def pending_sending(self, target_id, hash_):
        return self.pending


class FakeNotifier:
    def __init__(self) -> None:
        self.feed_posts = []

    def feed(self, text):
        self.feed_posts.append(text)
        return True


def make(mode: DeliveryMode, client=None, outbound=None, **kw):
    settings = Settings(
        database_url="postgresql://x:y@example.invalid/db",
        delivery_mode=mode,
        test_chat_guid=TEST_GUID,
        production_chat_guid=PROD_GUID,
        production_participant_fingerprint=participant_fingerprint(PROD_MEMBERS),
    )
    targets = FakeTargets(
        {
            DeliveryMode.TEST: DeliveryTarget(1, "test", TEST_GUID, None, "self-test"),
            DeliveryMode.PRODUCTION: DeliveryTarget(
                2,
                "production",
                PROD_GUID,
                participant_fingerprint(PROD_MEMBERS),
                "league",
            ),
        }
    )
    client = client or FakeClient()
    outbound = outbound or FakeOutbound()
    notifier = FakeNotifier()
    return (
        DeliveryService(settings, client, targets, outbound, notifier, **kw),
        client,
        outbound,
        notifier,
    )


def test_test_mode_sends_signed_to_test_chat_only() -> None:
    service, client, outbound, notifier = make(DeliveryMode.TEST)
    result = service.deliver(None, "self-test", "hello")
    assert result.status == "sent"
    assert client.sent == [(TEST_GUID, sign("hello"))]
    assert outbound.records[1]["state"] == "sent"
    assert len(notifier.feed_posts) == 1


def test_disabled_mode_sends_nothing() -> None:
    service, client, _, _ = make(DeliveryMode.DISABLED)
    with pytest.raises(DeliveryDisabled):
        service.deliver(None, "self-test", "hello")
    assert client.sent == []


def test_production_rejects_participant_change() -> None:
    client = FakeClient()
    client.participants[PROD_GUID] = PROD_MEMBERS + ["+15555550199"]
    service, client, outbound, _ = make(DeliveryMode.PRODUCTION, client=client)
    with pytest.raises(TargetMismatch):
        service.deliver(None, "self-test", "hello")
    assert client.sent == []
    assert outbound.records == {}


@pytest.mark.parametrize("run_id", [None, 41])
def test_crash_after_send_then_retry_reconciles(run_id) -> None:
    service, client, outbound, _ = make(DeliveryMode.TEST, crash_after_send=True)
    with pytest.raises(RuntimeError):
        service.deliver(run_id, "self-test", "hello")
    assert outbound.records[1]["state"] == "sending"
    outbound.pending = OutboundRecord(
        1,
        "sending",
        datetime.now(UTC),
        content_hash("hello"),
        None,
        run_id=run_id,
    )
    client.history = [
        InboundMessage(
            guid="g1",
            chat_guid=TEST_GUID,
            sender_address=None,
            text=sign("hello"),
            is_from_me=True,
            is_group=True,
            sent_at=datetime.now(UTC),
        )
    ]
    retry, _, _, retry_notifier = make(DeliveryMode.TEST, client=client, outbound=outbound)
    result = retry.deliver(run_id, "self-test", "hello")
    assert result.status == "reconciled"
    assert len(client.sent) == 1
    assert outbound.records[1]["state"] == "reconciled"
    reconciled_posts = [post for post in retry_notifier.feed_posts if "reconciled" in post]
    assert len(reconciled_posts) == 1


def test_reconciliation_ignores_whitespace_differences() -> None:
    service, client, outbound, _ = make(DeliveryMode.TEST, crash_after_send=True)
    with pytest.raises(RuntimeError):
        service.deliver(None, "self-test", "hello")
    assert outbound.records[1]["state"] == "sending"
    outbound.pending = OutboundRecord(
        1,
        "sending",
        datetime.now(UTC),
        content_hash("hello"),
        None,
    )
    signed = sign("hello")
    whitespace_variant = "  ".join(signed.split(" ")) + "\n"
    client.history = [
        InboundMessage(
            guid="g1",
            chat_guid=TEST_GUID,
            sender_address=None,
            text=whitespace_variant,
            is_from_me=True,
            is_group=True,
            sent_at=datetime.now(UTC),
        )
    ]
    retry, _, _, _ = make(DeliveryMode.TEST, client=client, outbound=outbound)
    result = retry.deliver(None, "self-test", "hello")
    assert result.status == "reconciled"
    assert len(client.sent) == 1
    assert outbound.records[1]["state"] == "reconciled"


def test_reservation_is_committed_before_send() -> None:
    """The reservation and the `sending` transition must both be durable before the
    send crosses the Messages boundary: a crash after send otherwise loses the
    reservation and the retry double-sends."""
    events: list[str] = []

    class RecordingClient(FakeClient):
        def send_text(self, chat_guid, text):
            events.append("send")
            return super().send_text(chat_guid, text)

    service, _client, outbound, _ = make(
        DeliveryMode.TEST,
        client=RecordingClient(),
        commit=lambda: events.append("commit"),
    )
    result = service.deliver(None, "self-test", "hello")
    assert result.status == "sent"
    assert events == ["commit", "commit", "send"]
    assert outbound.records[1]["state"] == "sent"


def test_delivery_without_commit_callback_still_sends() -> None:
    service, client, _, _ = make(DeliveryMode.TEST)
    assert service.deliver(None, "self-test", "hello").status == "sent"
    assert client.sent == [(TEST_GUID, sign("hello"))]


def test_deliver_attachment_reserves_sends_and_marks_sent() -> None:
    client = FakeClient()
    outbound = FakeOutbound()
    service, _, _, notifier = make(DeliveryMode.TEST, client=client, outbound=outbound)
    result = service.deliver_attachment(7, "league-agent", "bowers-hold-week-6.html", b"<p>x</p>")
    assert result.status == "sent"
    assert client.sent[-1] == (TEST_GUID, "bowers-hold-week-6.html", b"<p>x</p>")
    record = outbound.records[result.outbound_id]
    assert record["state"] == "sent" and record["guid"] == result.message_guid
    assert notifier.feed_posts[-1].endswith("bowers-hold-week-6.html")
    assert b"<p>x</p>" not in notifier.feed_posts[-1].encode()


def test_deliver_attachment_reconciles_a_crashed_send_by_filename() -> None:
    client = FakeClient()
    outbound = FakeOutbound()
    outbound.pending = OutboundRecord(
        3, "sending", datetime(2026, 9, 10, 12, 0, tzinfo=UTC), "hash", None
    )
    client.history = [
        InboundMessage(
            guid="p:0/BOT-3",
            chat_guid=TEST_GUID,
            sender_address=None,
            text="",
            is_from_me=True,
            is_group=True,
            sent_at=datetime(2026, 9, 10, 12, 0, 5, tzinfo=UTC),
            attachment_names=("bowers-hold-week-6.html",),
        )
    ]
    outbound.records[3] = {"state": "sending", "hash": "hash"}
    service, _, _, _ = make(DeliveryMode.TEST, client=client, outbound=outbound)
    result = service.deliver_attachment(7, "league-agent", "bowers-hold-week-6.html", b"x")
    assert result.status == "reconciled" and result.outbound_id == 3
    assert result.message_guid == "p:0/BOT-3"
    assert client.sent == []


def test_production_sends_a_file_asked_for_in_the_self_test_chat_there() -> None:
    service, client, _, _ = make(DeliveryMode.PRODUCTION)
    service.deliver_attachment(None, "trade-video", "clip.mp4", b"mp4", reply_to=TEST_GUID)
    assert client.sent[-1] == (TEST_GUID, "clip.mp4", b"mp4")
    service.deliver_attachment(None, "trade-video", "clip2.mp4", b"mp4", reply_to=None)
    assert client.sent[-1] == (PROD_GUID, "clip2.mp4", b"mp4")


def test_production_answers_the_self_test_chat_in_the_self_test_chat() -> None:
    """Ben (2026-09-10): the league chat is live, and the self-test chat keeps
    working for trying the bot out. A message from the self-test chat is answered
    there; anything else goes to the league chat."""
    service, client, _, _ = make(DeliveryMode.PRODUCTION)
    service.deliver(None, "trade-registrar", "hello", reply_to=TEST_GUID)
    assert client.sent == [(TEST_GUID, sign("hello"))]
    service.deliver(None, "trade-registrar", "league", reply_to=PROD_GUID)
    assert client.sent[-1] == (PROD_GUID, sign("league"))
    service.deliver(None, "trade-registrar", "elsewhere", reply_to="iMessage;+;chat-unknown")
    assert client.sent[-1] == (PROD_GUID, sign("elsewhere"))


@pytest.mark.parametrize("change", ["missing-config", "wrong-config", "missing-target"])
@pytest.mark.parametrize("attachment", [False, True])
def test_test_chat_reply_never_falls_back_to_production(change, attachment) -> None:
    service, client, outbound, _ = make(DeliveryMode.PRODUCTION)
    if change == "missing-target":
        service._targets.rows.pop(DeliveryMode.TEST)
    else:
        service._settings.test_chat_guid = None if change == "missing-config" else "other"
    with pytest.raises(TargetMismatch):
        if attachment:
            service.deliver_attachment(7, "league-agent", "answer.html", b"x", reply_to=TEST_GUID)
        else:
            service.deliver(7, "league-agent", "answer", reply_to=TEST_GUID)
    assert client.sent == []
    assert outbound.records == {}
