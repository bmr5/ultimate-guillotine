from datetime import UTC, datetime
from types import SimpleNamespace

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
    trigger = Trigger("ping", lambda m: m.text == "@daddy ping", lambda m: calls.append(m.guid))
    registry = TriggerRegistry()
    registry.register(trigger)
    sources = FakeSources()
    processor = InboundProcessor({CHAT}, registry, FakeReceipts(), sources)
    assert processor.process(msg("@daddy ping"), "e") == "handled:ping"
    assert calls == ["g1"]
    assert sources.rows[0].trigger_name == "ping"
    assert sources.rows[0].excerpt == "@daddy ping"


def test_blocked_member_cannot_run_any_bot_trigger() -> None:
    calls = []
    registry = TriggerRegistry()
    registry.register(Trigger("league-agent", lambda m: True, lambda m: calls.append(m.guid), requires_bot_access=True))
    sources = FakeSources()

    class Contacts:
        def member_for_handle_hash(self, digest):
            return SimpleNamespace(member_id=4)

    processor = InboundProcessor(
        {CHAT}, registry, FakeReceipts(), sources,
        contacts=Contacts(), blocked_member_ids=frozenset({4}),
    )
    assert processor.process(msg("@bot question"), "blocked-event") == "blocked_member"
    assert calls == [] and sources.rows == []


def test_member_allowlist_denies_other_and_unknown_senders() -> None:
    calls = []
    registry = TriggerRegistry()
    registry.register(Trigger("league-agent", lambda m: True, lambda m: calls.append(m.guid), requires_bot_access=True))
    sources = FakeSources()

    class Contacts:
        def member_for_handle_hash(self, digest):
            if digest == handle_hash("+15555550100"):
                return SimpleNamespace(member_id=11)
            if digest == handle_hash("+15555550101"):
                return SimpleNamespace(member_id=4)
            return None

    from ultimate_guillotine.data.repositories import handle_hash

    processor = InboundProcessor(
        {CHAT}, registry, FakeReceipts(), sources,
        contacts=Contacts(), allowed_member_ids=frozenset({11}),
    )
    assert processor.process(msg("@bot mine", guid="mine"), "e1") == "handled:league-agent"
    assert processor.process(
        msg("@bot other", guid="other").model_copy(update={"sender_address": "+15555550101"}), "e2"
    ) == "blocked_member"
    assert processor.process(
        msg("@bot unknown", guid="unknown").model_copy(update={"sender_address": None}), "e3"
    ) == "blocked_member"
    assert processor.process(msg("@bot mac", from_me=True, guid="mac"), "e4") == "handled:league-agent"
    assert calls == ["mine", "mac"]
    assert [row.source_guid for row in sources.rows] == ["mine", "mac"]


def test_restricted_member_trade_alert_still_logs_without_running_bot() -> None:
    calls = []
    registry = TriggerRegistry()
    registry.register(Trigger("trade-registrar", lambda m: m.text.startswith("🚨"),
                              lambda m: calls.append("trade")))
    registry.register(Trigger("league-agent", lambda m: "@bot" in m.text,
                              lambda m: calls.append("bot"), requires_bot_access=True))
    sources = FakeSources()

    class Contacts:
        def member_for_handle_hash(self, digest):
            return SimpleNamespace(member_id=4)

    processor = InboundProcessor(
        {CHAT}, registry, FakeReceipts(), sources,
        contacts=Contacts(), allowed_member_ids=frozenset({10, 11, 13}),
    )
    assert processor.process(msg("🚨 trade alert @bot", guid="trade"), "e") == "handled:trade-registrar"
    assert calls == ["trade"]
    assert sources.rows[0].trigger_name == "trade-registrar"


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


def test_ping_trigger_accepts_unsigned_messages_from_ben_but_not_signed_ones() -> None:
    from ultimate_guillotine.core.signature import sign
    from ultimate_guillotine.listener.processing import ping_trigger

    calls = []

    class Delivery:
        def deliver(self, run_id, agent, content):
            calls.append(content)

    trigger = ping_trigger(Delivery(), CHAT)
    assert trigger.matches(msg("@daddy ping", from_me=True))
    assert trigger.matches(msg("@daddy PING"))
    processor = build(trigger)
    assert processor.process(msg(sign("pong 1"), from_me=True), "e1") == "ignored_bot"
    assert processor.process(msg("@daddy ping", from_me=True), "e2") == "handled:ping"
    assert len(calls) == 1


def test_verbatim_trade_confirmation_echo_does_not_run_triggers() -> None:
    calls = []
    trigger = Trigger("reply", lambda m: True, lambda m: calls.append(m.guid))
    assert build(trigger).process(
        msg("trade recorded in database", from_me=True), "confirmation-echo"
    ) == "ignored_bot"
    assert calls == []
