from datetime import UTC, datetime, timedelta

from ultimate_guillotine.data.repositories import ExpectedRun
from ultimate_guillotine.ops.health import check_health

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


class FakeBeats:
    def __init__(self, stale):
        self._stale = stale

    def stale(self, older_than, now):
        return self._stale


class FakeRuns:
    def __init__(self, last):
        self._last = last

    def last_started(self, agent):
        return self._last.get(agent)


class FakeExpected:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeClient:
    def __init__(self, ok):
        self._ok = ok

    def ping(self):
        return self._ok


class FakeOutbound:
    def __init__(self, stuck=()):
        self._stuck = list(stuck)

    def stuck_sending(self, older_than, now):
        return self._stuck


def test_healthy_system_reports_nothing() -> None:
    expected = FakeExpected([ExpectedRun("guillotine-health", "health", 15, "every 5m")])
    runs = FakeRuns({"health": NOW - timedelta(minutes=4)})
    assert check_health(NOW, FakeBeats([]), runs, expected, FakeClient(True), FakeOutbound()) == []


def test_reports_stale_heartbeat_missed_run_and_bluebubbles() -> None:
    expected = FakeExpected([ExpectedRun("guillotine-health", "health", 15, "every 5m")])
    runs = FakeRuns({"health": NOW - timedelta(minutes=40)})
    problems = check_health(
        NOW, FakeBeats(["listener"]), runs, expected, FakeClient(False), FakeOutbound()
    )
    assert any("listener" in p for p in problems)
    assert any("guillotine-health" in p and "40" in p for p in problems)
    assert any("BlueBubbles" in p for p in problems)


def test_never_run_job_is_reported() -> None:
    expected = FakeExpected([ExpectedRun("guillotine-gap-fill", "gap-fill", 15, "every 3m")])
    problems = check_health(
        NOW, FakeBeats([]), FakeRuns({}), expected, FakeClient(True), FakeOutbound()
    )
    assert problems == ["Expected job guillotine-gap-fill has never run"]


def test_reports_outbound_messages_stuck_in_sending() -> None:
    """A row left in `sending` means a send crossed the Messages boundary without a
    recorded outcome; Ben has to look at the chat, so it belongs in the health report."""
    expected = FakeExpected([])
    problems = check_health(
        NOW, FakeBeats([]), FakeRuns({}), expected, FakeClient(True), FakeOutbound([12, 13])
    )
    assert problems == [
        "Outbound message #12 stuck in sending",
        "Outbound message #13 stuck in sending",
    ]
