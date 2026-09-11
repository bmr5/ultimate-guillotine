from datetime import UTC, datetime

import pytest

from ultimate_guillotine.config import DeliveryMode, Settings
from ultimate_guillotine.core.signature import sign
from ultimate_guillotine.data.repositories import DeliveryTarget, OutboundRecord
from ultimate_guillotine.messages.bluebubbles import BlueBubblesError, InboundMessage
from ultimate_guillotine.messages.delivery import (
    DeliveryDisabled,
    DeliveryService,
    TargetMismatch,
    attachment_hash,
    content_hash,
)
from ultimate_guillotine.messages.fingerprint import participant_fingerprint

TEST_GUID = "iMessage;+;chat-test"
PROD_GUID = "iMessage;+;chat-prod"
PROD_MEMBERS = ["+15555550100", "+15555550101"]


class FakeClient:
    def __init__(self) -> None:
        self.sent = []
        self.reactions = []
        self.participants = {PROD_GUID: PROD_MEMBERS, TEST_GUID: ["+15555550100"]}
        self.history = []
        self.reply_guids = []
        self.info = {"private_api": True, "helper_connected": True}
        self.messages = {}
        self.lookups = []

    def server_info(self):
        return self.info

    def get_message(self, guid):
        self.lookups.append(guid)
        return self.messages.get(guid)

    def chat_participants(self, chat_guid):
        return self.participants[chat_guid]

    def send_text(self, chat_guid, text, *, reply_to_message_guid=None):
        self.sent.append((chat_guid, text))
        self.reply_guids.append(reply_to_message_guid)
        return f"guid-{len(self.sent)}"

    def send_reaction(self, chat_guid, message_guid):
        self.reactions.append((chat_guid, message_guid))
        return f"reaction-{len(self.reactions)}"

    def send_attachment(
        self, chat_guid, filename, data, mime="text/html", *, reply_to_message_guid=None
    ):
        self.sent.append((chat_guid, filename, data))
        self.reply_guids.append(reply_to_message_guid)
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


def video_request(guid="request-1", chat=TEST_GUID, thread=None):
    return InboundMessage(
        guid=guid,
        chat_guid=chat,
        sender_address=None,
        text="@daddy create trade video",
        is_from_me=False,
        is_group=True,
        sent_at=datetime.now(UTC),
        thread_originator_guid=thread,
    )


@pytest.mark.parametrize("chat", [TEST_GUID, PROD_GUID])
def test_video_acknowledgement_replies_to_request_in_the_correct_chat(chat) -> None:
    service, client, outbound, _ = make(DeliveryMode.PRODUCTION)
    request = video_request(chat=chat, thread="trade-alert")
    result = service.deliver(
        None, "trade-video", "On it kitten", reply_to=chat, reply_to_message=request
    )
    assert client.sent == [(chat, sign("On it kitten"))]
    assert client.reply_guids == ["request-1"]
    assert outbound.records[result.outbound_id]["hash"] == content_hash("On it kitten", "request-1")
    assert content_hash("On it kitten", "request-1") != content_hash("On it kitten", "request-2")


@pytest.mark.parametrize(
    "info",
    [
        {"private_api": False, "helper_connected": False},
        {"private_api": True, "helper_connected": False},
    ],
)
def test_reply_unavailable_keeps_the_existing_acknowledgement(info) -> None:
    service, client, _, _ = make(DeliveryMode.TEST)
    client.info = info
    service.deliver(None, "trade-video", "On it kitten", reply_to_message=video_request())
    assert client.sent == [(TEST_GUID, sign("On it kitten"))]
    assert client.reply_guids == [None]


def test_failed_capability_check_does_not_lose_the_acknowledgement() -> None:
    class Client(FakeClient):
        def server_info(self):
            raise BlueBubblesError("unavailable")

    service, client, _, _ = make(DeliveryMode.TEST, client=Client())
    service.deliver(None, "trade-video", "On it kitten", reply_to_message=video_request())
    assert client.reply_guids == [None]


def test_redirected_delivery_does_not_reply_to_a_message_in_another_chat() -> None:
    service, client, _, _ = make(DeliveryMode.TEST)
    service.deliver(
        None,
        "trade-video",
        "On it kitten",
        reply_to=PROD_GUID,
        reply_to_message=video_request(chat=PROD_GUID),
    )
    assert client.sent == [(TEST_GUID, sign("On it kitten"))]
    assert client.reply_guids == [None]


def test_reply_reconciliation_ignores_identical_acknowledgements_in_other_threads() -> None:
    service, client, outbound, _ = make(DeliveryMode.TEST, crash_after_send=True)
    request = video_request(thread="trade-alert")
    with pytest.raises(RuntimeError):
        service.deliver(None, "trade-video", "On it kitten", reply_to_message=request)
    outbound.pending = OutboundRecord(
        1, "sending", datetime.now(UTC), content_hash("On it kitten", request.guid), None
    )
    client.history = [
        video_request(guid="wrong-reply", thread="different-alert").model_copy(
            update={"is_from_me": True, "text": sign("On it kitten")}
        ),
        video_request(guid="right-reply", thread="p:0/trade-alert").model_copy(
            update={"is_from_me": True, "text": sign("On it kitten")}
        ),
    ]
    retry, _, _, _ = make(DeliveryMode.TEST, client=client, outbound=outbound)
    result = retry.deliver(None, "trade-video", "On it kitten", reply_to_message=request)
    assert result.status == "reconciled" and result.message_guid == "right-reply"
    assert len(client.sent) == 1


def test_failed_reply_send_is_not_retried_as_a_standalone_message() -> None:
    class Client(FakeClient):
        def send_text(self, *args, **kwargs):
            super().send_text(*args, **kwargs)
            raise BlueBubblesError("send timed out")

    service, client, outbound, _ = make(DeliveryMode.TEST, client=Client())
    with pytest.raises(BlueBubblesError):
        service.deliver(None, "trade-video", "On it kitten", reply_to_message=video_request())
    assert client.reply_guids == ["request-1"]
    assert outbound.records[1]["state"] == "sending"


@pytest.mark.parametrize("chat", [TEST_GUID, PROD_GUID])
def test_video_file_replies_to_the_original_request_in_its_chat(chat) -> None:
    service, client, outbound, _ = make(DeliveryMode.PRODUCTION)
    client.messages["request-1"] = video_request(chat=chat, thread="trade-alert")
    result = service.deliver_attachment(
        None,
        "trade-video",
        "clip.mp4",
        b"mp4",
        reply_to=chat,
        reply_to_message_guid="request-1",
    )
    assert client.sent == [(chat, "clip.mp4", b"mp4")]
    assert client.reply_guids == ["request-1"]
    assert outbound.records[result.outbound_id]["hash"] == attachment_hash(b"mp4", "request-1")
    assert attachment_hash(b"mp4", "request-1") != attachment_hash(b"mp4", "request-2")


@pytest.mark.parametrize(
    "reason", ["disabled", "disconnected", "redirected", "missing", "wrong-chat", "lookup-error"]
)
def test_video_file_still_sends_normally_when_reply_is_unavailable(reason) -> None:
    service, client, _, _ = make(DeliveryMode.TEST)
    chat = TEST_GUID
    client.messages["request-1"] = video_request()
    if reason == "disabled":
        client.info["private_api"] = False
    elif reason == "disconnected":
        client.info["helper_connected"] = False
    elif reason == "redirected":
        chat = PROD_GUID
    elif reason == "missing":
        client.messages.clear()
    elif reason == "wrong-chat":
        client.messages["request-1"] = video_request(chat=PROD_GUID)
    else:

        def failed_lookup(_guid):
            raise BlueBubblesError("lookup unavailable")

        client.get_message = failed_lookup
    service.deliver_attachment(
        None,
        "trade-video",
        "clip.mp4",
        b"mp4",
        reply_to=chat,
        reply_to_message_guid="request-1",
    )
    assert client.sent == [(TEST_GUID, "clip.mp4", b"mp4")]
    assert client.reply_guids == [None]
    if reason in ("disabled", "disconnected", "redirected"):
        assert client.lookups == []


def test_video_reply_reconciles_only_in_the_original_requests_thread() -> None:
    service, client, outbound, _ = make(DeliveryMode.TEST, crash_after_send=True)
    client.messages["request-1"] = video_request(thread="trade-alert")
    with pytest.raises(RuntimeError):
        service.deliver_attachment(
            None,
            "trade-video",
            "clip.mp4",
            b"mp4",
            reply_to=TEST_GUID,
            reply_to_message_guid="request-1",
        )
    outbound.pending = OutboundRecord(
        1, "sending", datetime.now(UTC), attachment_hash(b"mp4", "request-1"), None
    )
    client.history = [
        video_request(guid=guid, thread=thread).model_copy(
            update={"is_from_me": True, "text": "", "attachment_names": ("clip.mp4",)}
        )
        for guid, thread in (("wrong-video", "other-alert"), ("right-video", "p:0/trade-alert"))
    ]
    retry, _, _, _ = make(DeliveryMode.TEST, client=client, outbound=outbound)
    result = retry.deliver_attachment(
        None,
        "trade-video",
        "clip.mp4",
        b"mp4",
        reply_to=TEST_GUID,
        reply_to_message_guid="request-1",
    )
    assert result.status == "reconciled" and result.message_guid == "right-video"
    assert len(client.sent) == 1


def test_each_trade_gets_the_exact_database_confirmation() -> None:
    client = FakeClient()
    service, _, outbound, _ = make(DeliveryMode.TEST, client=client)
    first = service.deliver(1, "trade-registrar", "trade recorded in database")
    second = service.deliver(2, "trade-registrar", "trade recorded in database")
    assert client.sent == [(TEST_GUID, "trade recorded in database")] * 2
    assert first.outbound_id != second.outbound_id
    assert all(row["state"] == "sent" for row in outbound.records.values())


@pytest.mark.parametrize("chat", [TEST_GUID, PROD_GUID])
def test_reaction_stays_in_the_request_chat_and_is_recorded(chat):
    service, client, outbound, _ = make(DeliveryMode.PRODUCTION)
    result = service.react(7, video_request(chat=chat))
    assert client.reactions == [(chat, "request-1")]
    assert client.sent == []
    assert outbound.records[result.outbound_id]["state"] == "sent"


@pytest.mark.parametrize("private_api,helper", [(False, False), (True, False), (False, True)])
def test_unavailable_reactions_do_not_send_fallback_text(private_api, helper):
    service, client, outbound, _ = make(DeliveryMode.TEST)
    client.info = {"private_api": private_api, "helper_connected": helper}
    assert service.react(7, video_request()) is None
    assert client.sent == client.reactions == []
    assert outbound.records == {}


def test_reaction_cannot_be_redirected_between_chats():
    service, client, _, _ = make(DeliveryMode.TEST)
    with pytest.raises(TargetMismatch):
        service.react(7, video_request(chat=PROD_GUID))
    assert client.sent == client.reactions == []


def test_failed_reaction_is_recorded_without_fallback_text():
    service, client, outbound, _ = make(DeliveryMode.TEST)
    def fail(*args):
        raise BlueBubblesError("reaction failed")
    client.send_reaction = fail
    with pytest.raises(BlueBubblesError):
        service.react(7, video_request())
    assert client.sent == []
    assert outbound.records[1]["state"] == "failed"


def test_disabled_delivery_cannot_react():
    service, client, _, _ = make(DeliveryMode.DISABLED)
    with pytest.raises(DeliveryDisabled):
        service.react(7, video_request())
    assert client.sent == client.reactions == []
