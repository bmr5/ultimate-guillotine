"""`ug ingest gap-fill` is the safety net for a listener restart, so it must not
go blind.

Two ways it could: an unbounded `since` taken from the last *qualifying* message
(source_messages only holds those, so it can sit days in the past), and a single
page of 100 messages, which silently drops everything past the hundredth.
"""

import threading
from datetime import UTC, datetime, timedelta

import pytest

from ultimate_guillotine.agent.worker import AgentWorker, Job
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
            lambda settings, conn, c, delivery, notifier, **kw: (processor, {GUID}),
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


@pytest.mark.parametrize("replay_fails", [False, True])
def test_gap_fill_waits_for_accepted_jobs_even_when_replay_fails(
    harness, monkeypatch, replay_fails,
) -> None:
    install, _processor, _state = harness
    install(FakeClient([3]))
    started, release = threading.Event(), threading.Event()
    replay_finished, returned = threading.Event(), threading.Event()
    completed, results, errors, reconciliations = [], [], [], []
    worker = AgentWorker(
        client=None, source=None, delivery=None, notifier=None,
        runs=None, sessions=None, answers=None,
    )

    def run_job(job):
        started.set()
        assert release.wait(5)
        completed.append(job.run_id)

    monkeypatch.setattr(worker, "run_job", run_job)

    def build_worker(settings, client, notifier, chat_guid, *, reconcile):
        assert chat_guid == GUID
        reconciliations.append(reconcile)
        worker.start()
        return worker

    monkeypatch.setattr(ingest_module, "build_agent_worker", build_worker, raising=False)

    def build_processor(settings, conn, client, delivery, notifier, *, agent_worker_factory=None):
        active = (
            agent_worker_factory(GUID) if agent_worker_factory else
            build_worker(settings, client, notifier, GUID, reconcile=False)
        )

        class Processor:
            def process(self, msg, event_id):
                if msg.guid == "msg-2":
                    replay_finished.set()
                    if replay_fails:
                        raise ValueError("replay failed")
                    return "no_trigger"
                active.submit(Job(int(msg.guid[-1]), msg, None, None))
                return "handled:league-agent"

        return Processor(), {GUID}

    monkeypatch.setattr(ingest_module, "build_processor", build_processor)

    def run_gap_fill():
        try:
            results.append(ingest_module.cmd_gap_fill(_args()))
        except Exception as exc:  # noqa: BLE001 - surface thread failures in the test
            errors.append(exc)
        finally:
            returned.set()

    command = threading.Thread(target=run_gap_fill, daemon=True)
    command.start()
    try:
        assert started.wait(2)
        assert replay_finished.wait(2)
        assert not returned.wait(0.1), "gap-fill returned with accepted jobs unfinished"
    finally:
        release.set()
        command.join(2)
    assert returned.is_set()
    assert completed == [0, 1]
    assert reconciliations == [False]
    if replay_fails:
        assert results == []
        assert len(errors) == 1 and isinstance(errors[0], ValueError)
    else:
        assert results == [0] and errors == []
