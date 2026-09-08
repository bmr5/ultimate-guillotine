from datetime import UTC, datetime

from ultimate_guillotine.core.signature import sign
from ultimate_guillotine.listener.processing import InboundProcessor, Trigger, TriggerRegistry
from ultimate_guillotine.messages.bluebubbles import InboundMessage

CHAT = "iMessage;+;chat-test"


def msg(text, chat=CHAT, from_me=False, guid="g1"):
    return InboundMessage(
        guid=guid,
        chat_guid=chat,
        sender_address="+15555550100",
        text=text,
        is_from_me=from_me,
        is_group=True,
        sent_at=datetime.now(UTC),
    )


class FakeReceipts:
    def __init__(self):
        self.seen = set()

    def record(self, event_id, outcome):
        if event_id in self.seen:
            return False
        self.seen.add(event_id)
        return True


class FakeSources:
    def __init__(self):
        self.rows = []

    def upsert(self, row):
        self.rows.append(row)
        return True


def build(trigger=None):
    registry = TriggerRegistry()
    if trigger:
        registry.register(trigger)
    return InboundProcessor({CHAT}, registry, FakeReceipts(), FakeSources())


def test_duplicate_event_is_dropped() -> None:
    processor = build()
    assert processor.process(msg("hi"), "evt") == "no_trigger"
    assert processor.process(msg("hi"), "evt") == "duplicate"


def test_unlisted_chat_is_ignored() -> None:
    assert build().process(msg("hi", chat="iMessage;+;other"), "e") == "ignored_chat"


def test_signed_bot_message_is_ignored() -> None:
    assert build().process(msg(sign("hello"), from_me=True), "e") == "ignored_bot"


def test_matching_trigger_runs_and_persists_source() -> None:
    calls = []
    trigger = Trigger("ping", lambda m: m.text == "bot: ping", lambda m: calls.append(m.guid))
    registry = TriggerRegistry()
    registry.register(trigger)
    sources = FakeSources()
    processor = InboundProcessor({CHAT}, registry, FakeReceipts(), sources)
    assert processor.process(msg("bot: ping"), "e") == "handled:ping"
    assert calls == ["g1"]
    assert sources.rows[0].trigger_name == "ping"
    assert sources.rows[0].excerpt == "bot: ping"


def test_handler_error_is_reported_not_raised() -> None:
    errors = []

    def boom(m):
        raise RuntimeError("x")

    registry = TriggerRegistry()
    registry.register(Trigger("boom", lambda m: True, boom))
    processor = InboundProcessor(
        {CHAT},
        registry,
        FakeReceipts(),
        FakeSources(),
        on_error=lambda name, exc: errors.append(name),
    )
    assert processor.process(msg("hi"), "e") == "handled:boom"
    assert errors == ["boom"]
