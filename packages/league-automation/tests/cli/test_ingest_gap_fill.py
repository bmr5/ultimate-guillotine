"""`ug ingest gap-fill` is the safety net for a listener restart, so it must not
go blind.

Two ways it could: an unbounded `since` taken from the last *qualifying* message
(source_messages only holds those, so it can sit days in the past), and a single
page of 100 messages, which silently drops everything past the hundredth.
"""

from datetime import UTC, datetime, timedelta

import pytest

from ultimate_guillotine.cli import ingest as ingest_module

NOW = datetime(2026, 9, 8, 23, 47, tzinfo=UTC)
GUID = "iMessage;+;chat-test"


class FakeMessage:
    def __init__(self, index: int, sent_at: datetime) -> None:
        self.guid = f"msg-{index}"
        self.sent_at = sent_at


class FakeClient:
    """Serves 100 messages then 3, so the caller must ask twice to see them all."""

    def __init__(self, page_sizes) -> None:
        self.page_sizes = list(page_sizes)
        self.calls: list[tuple[str, datetime, int]] = []
        self._next_index = 0

    def messages_after(self, chat_guid, after, limit=100):
        self.calls.append((chat_guid, after, limit))
        if not self.page_sizes:
            return []
        size = self.page_sizes.pop(0)
        page = [
            FakeMessage(self._next_index + i, NOW - timedelta(minutes=30) + timedelta(seconds=i))
            for i in range(size)
        ]
        self._next_index += size
        return page


class FakeProcessor:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def process(self, msg, event_id):
        self.seen.append(msg.guid)
        return "handled:ping" if msg.guid == "msg-0" else "no_trigger"


class FakeSources:
    def __init__(self, latest) -> None:
        self._latest = latest

    def latest_sent_at(self, chat_guid_hash):
        return self._latest


class FakeDeps:
    def __init__(self, client) -> None:
        self.settings = object()
        self.conn = object()
        self.client = client
        self.notifier = object()


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch):
    processor = FakeProcessor()
    state = {"latest": None}

    class FrozenDatetime:
        @staticmethod
        def now(tz):
            return NOW

    def install(client):
        monkeypatch.setattr(ingest_module, "datetime", FrozenDatetime)
        monkeypatch.setattr(ingest_module, "build_deps", lambda: FakeDeps(client))
        monkeypatch.setattr(ingest_module, "build_delivery", lambda deps: object())
        monkeypatch.setattr(
            ingest_module,
            "build_processor",
            lambda settings, conn, c, delivery, notifier: (processor, {GUID}),
        )
        monkeypatch.setattr(
            ingest_module, "SourceMessageRepository", lambda conn: FakeSources(state["latest"])
        )
        monkeypatch.setattr(
            ingest_module,
            "run_scheduled",
            lambda conn, agent, now, action, **kw: action(1),
        )

    return install, processor, state


def _args(since_minutes: int = 60):
    return type("Args", (), {"since_minutes": since_minutes})()


def test_gap_fill_pages_until_a_short_page(harness) -> None:
    install, processor, _state = harness
    client = FakeClient([100, 3])
    install(client)

    assert ingest_module.cmd_gap_fill(_args()) == 0

    # Two pages fetched, and the second starts just after the last message of the first.
    assert len(client.calls) == 2
    assert [limit for _, _, limit in client.calls] == [100, 100]
    first_page_last_sent = NOW - timedelta(minutes=30) + timedelta(seconds=99)
    assert client.calls[1][1] == first_page_last_sent + timedelta(milliseconds=1)
    assert len(processor.seen) == 103


def test_gap_fill_window_never_reaches_further_back_than_since_minutes(harness) -> None:
    """`latest_sent_at` only tracks qualifying messages, so it can be days old. The
    window floor keeps the replay bounded instead of scanning the whole history."""
    install, _processor, state = harness
    state["latest"] = NOW - timedelta(days=5)
    client = FakeClient([2])
    install(client)

    assert ingest_module.cmd_gap_fill(_args(since_minutes=60)) == 0
    assert client.calls[0][1] == NOW - timedelta(minutes=60)


def test_gap_fill_resumes_from_the_last_recorded_message_when_it_is_recent(harness) -> None:
    install, _processor, state = harness
    state["latest"] = NOW - timedelta(minutes=5)
    client = FakeClient([1])
    install(client)

    assert ingest_module.cmd_gap_fill(_args(since_minutes=60)) == 0
    assert client.calls[0][1] == NOW - timedelta(minutes=5)


def test_gap_fill_stops_at_the_page_cap(harness) -> None:
    install, _processor, _state = harness
    client = FakeClient([100] * 40)
    install(client)

    assert ingest_module.cmd_gap_fill(_args()) == 0
    assert len(client.calls) == ingest_module.MAX_GAP_FILL_PAGES
