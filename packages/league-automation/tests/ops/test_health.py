from datetime import UTC, datetime, timedelta

from ultimate_guillotine.data.repositories import ExpectedRun
from ultimate_guillotine.ops.health import check_health, failing_agents, missed_runs

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


class FakeBeats:
    def __init__(self, stale):
        self._stale = stale

    def stale(self, older_than, now):
        return self._stale


class FakeRuns:
    def __init__(self, last, stuck=(), finished=None):
        self._last = last
        self._stuck = list(stuck)
        self._finished = finished or {}

    def last_started(self, agent):
        return self._last.get(agent)

    def last_finished_status(self, agent):
        return self._finished.get(agent)

    def stale_running(self, older_than, now):
        return self._stuck


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


def test_reports_runs_left_running() -> None:
    """A run still `running` long after it started means an agent died mid-flight:
    the audit trail says nothing happened, and `ug trades retry` is the remedy."""
    runs = FakeRuns({}, stuck=[("trade-registrar", "trade:g1"), ("trade-registrar", "trade:g2")])
    problems = check_health(
        NOW, FakeBeats([]), runs, FakeExpected([]), FakeClient(True), FakeOutbound()
    )
    assert problems == ["runs stuck running > 15m: 2 (agent trade-registrar)"]


def _projections_jobs(gaps=(90, 90, 90, 90)):
    """The four cron rows that share the `projections-sync` agent on purpose."""
    names = (
        "guillotine-sleeper-projections",
        "guillotine-sleeper-projections-monday",
        "guillotine-sleeper-projections-sunday",
        "guillotine-sleeper-projections-thursday",
    )
    return FakeExpected(
        [
            ExpectedRun(name, "projections-sync", gap, "*/5 * * * *")
            for name, gap in zip(names, gaps, strict=True)
        ]
    )


def test_four_cron_rows_sharing_one_agent_are_one_missed_line() -> None:
    """The projections baseline and its three game-window bursts share an agent and
    therefore a run history. One silence is one problem, not four."""
    runs = FakeRuns({"projections-sync": NOW - timedelta(minutes=200)})

    assert missed_runs(NOW, runs, _projections_jobs()) == [
        "Expected job guillotine-sleeper-projections last ran 200 minutes ago (limit 90)"
    ]


def test_a_never_run_shared_agent_is_also_one_line() -> None:
    assert missed_runs(NOW, FakeRuns({}), _projections_jobs()) == [
        "Expected job guillotine-sleeper-projections has never run"
    ]


def test_the_line_quotes_the_tightest_budget_of_the_agents_jobs() -> None:
    """The tightest gap is the deadline the silence broke first, so that is the one
    the report has to be measured against -- a laxer sibling row must not hide it."""
    jobs = _projections_jobs(gaps=(240, 240, 45, 240))
    runs = FakeRuns({"projections-sync": NOW - timedelta(minutes=60)})

    assert missed_runs(NOW, runs, jobs) == [
        ("Expected job guillotine-sleeper-projections-sunday last ran 60 minutes ago (limit 45)")
    ]


def test_an_agent_inside_its_tightest_budget_is_not_reported() -> None:
    runs = FakeRuns({"projections-sync": NOW - timedelta(minutes=20)})

    assert missed_runs(NOW, runs, _projections_jobs()) == []


def test_an_agent_whose_last_finished_run_failed_is_reported() -> None:
    """A job that fires every five minutes and fails every five minutes keeps
    `last_started` moving, so no gap budget is ever broken and `missed_runs` sees
    a healthy agent. The standing status is what makes the outage visible."""
    runs = FakeRuns(
        {"projections-sync": NOW - timedelta(minutes=4)},
        finished={"projections-sync": "failed"},
    )

    assert failing_agents(runs, _projections_jobs()) == [
        "projections-sync: last run failed at 2026-09-08 11:56 UTC"
    ]
    assert check_health(
        NOW, FakeBeats([]), runs, _projections_jobs(), FakeClient(True), FakeOutbound()
    ) == ["projections-sync: last run failed at 2026-09-08 11:56 UTC"]


def test_a_succeeding_or_never_finished_agent_is_not_reported() -> None:
    fresh = {"projections-sync": NOW - timedelta(minutes=4)}

    assert failing_agents(FakeRuns(fresh), _projections_jobs()) == []
    assert (
        failing_agents(
            FakeRuns(fresh, finished={"projections-sync": "succeeded"}), _projections_jobs()
        )
        == []
    )


def test_four_cron_rows_sharing_one_agent_are_one_failure_line() -> None:
    """The same reason `missed_runs` reports per agent: one thing is wrong once."""
    runs = FakeRuns(
        {"projections-sync": NOW - timedelta(minutes=4)},
        finished={"projections-sync": "failed", "health": "failed"},
    )

    # `health` has no expected-runs row here, so it is not one of the scheduled
    # jobs this check speaks for.
    assert failing_agents(runs, _projections_jobs()) == [
        "projections-sync: last run failed at 2026-09-08 11:56 UTC"
    ]


def test_a_job_registered_inside_its_budget_is_not_late_yet() -> None:
    """A nightly job installed at noon has no run to show until 11:50 PM, and the
    5-minute health check would otherwise page the alerts channel every fire until
    then. Registered more recently than its own gap budget, silence is on time."""
    expected = FakeExpected(
        [
            ExpectedRun(
                "guillotine-eod-summary",
                "eod-summary",
                1500,
                "50 23 * * *",
                created_at=NOW - timedelta(hours=1),
            )
        ]
    )
    assert missed_runs(NOW, FakeRuns({}), expected) == []


def test_a_job_registered_longer_ago_than_its_budget_and_never_run_is_reported() -> None:
    expected = FakeExpected(
        [
            ExpectedRun(
                "guillotine-eod-summary",
                "eod-summary",
                1500,
                "50 23 * * *",
                created_at=NOW - timedelta(hours=26),
            )
        ]
    )
    assert missed_runs(NOW, FakeRuns({}), expected) == [
        "Expected job guillotine-eod-summary has never run"
    ]


def test_a_job_with_no_registration_time_on_file_is_reported_as_before() -> None:
    expected = FakeExpected([ExpectedRun("guillotine-gap-fill", "gap-fill", 15, "every 3m")])
    assert missed_runs(NOW, FakeRuns({}), expected) == [
        "Expected job guillotine-gap-fill has never run"
    ]
