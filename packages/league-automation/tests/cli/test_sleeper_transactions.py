"""What `ug sleeper transactions` does around the sync it wraps: which weeks it asks for,
the off-season no-op, the agent it records under, and the notes it posts."""

import argparse
import subprocess
import sys
from collections import Counter
from types import SimpleNamespace

import pytest

from ultimate_guillotine.cli import sleeper as sleeper_cli
from ultimate_guillotine.sleeper.transactions import TransactionReport

from .test_sleeper_scores import FakeConn, FakeNotifier


def _report(weeks: list[int], **overrides) -> TransactionReport:
    return TransactionReport(**{"transactions": 8, "moves": 14, "weeks": weeks, **overrides})


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    conn: FakeConn,
    season_type: str = "regular",
    season: int = 2026,
    week: int = 3,
    report_overrides: dict | None = None,
    agents: list[str] | None = None,
) -> tuple[FakeNotifier, list[list[int]]]:
    notifier = FakeNotifier()
    monkeypatch.setattr(
        sleeper_cli,
        "build_deps",
        lambda: SimpleNamespace(
            conn=conn, notifier=notifier, settings=SimpleNamespace(sleeper_league_id="league-1")
        ),
    )
    monkeypatch.setattr(sleeper_cli.httpx, "Client", lambda: object())
    monkeypatch.setattr(sleeper_cli, "SleeperClient", lambda http: object())
    monkeypatch.setattr(
        sleeper_cli,
        "current_week",
        lambda client, conn, now: SimpleNamespace(
            season=season, season_type=season_type, week=week
        ),
    )
    asked: list[list[int]] = []

    def fake_sync(client, target, league_id, season_id, weeks, now):
        asked.append(list(weeks))
        return _report(list(weeks), **(report_overrides or {}))

    monkeypatch.setattr(sleeper_cli, "sync_transactions", fake_sync)

    def fake_runner(deps, agent, now, action):
        if agents is not None:
            agents.append(agent)
        return action(1)

    monkeypatch.setattr(sleeper_cli, "run_scheduled_with_notes", fake_runner)
    return notifier, asked


def _args(**overrides) -> argparse.Namespace:
    return argparse.Namespace(**{"week": None, "all": False, "quiet": True, **overrides})


def test_transactions_help_lists_week_and_all() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ultimate_guillotine.cli.main",
            "sleeper",
            "transactions",
            "--help",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--week" in result.stdout
    assert "--all" in result.stdout


def test_the_default_is_the_previous_and_current_week() -> None:
    assert sleeper_cli.weeks_to_sync(3, None, False) == [2, 3]


def test_week_one_has_no_previous_week() -> None:
    assert sleeper_cli.weeks_to_sync(1, None, False) == [1]


def test_all_walks_from_week_one() -> None:
    assert sleeper_cli.weeks_to_sync(4, None, True) == [1, 2, 3, 4]


def test_an_explicit_week_is_just_that_week() -> None:
    assert sleeper_cli.weeks_to_sync(4, 2, False) == [2]


def test_the_weeks_asked_of_the_sync_follow_the_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _notifier, asked = _wire(monkeypatch, conn=FakeConn(), week=5)
    assert sleeper_cli.cmd_transactions(_args()) == 0
    assert asked == [[4, 5]]


def test_the_season_row_is_looked_up_by_the_state_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConn()
    _wire(monkeypatch, conn=conn, season=2027)
    sleeper_cli.cmd_transactions(_args())
    assert conn.queries[0][1] == (2027,)


def test_a_preseason_run_is_a_clean_no_op(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _notifier, asked = _wire(monkeypatch, conn=FakeConn(), season_type="pre")
    assert sleeper_cli.cmd_transactions(_args(quiet=False)) == 0
    assert asked == []
    assert capsys.readouterr().out == "transactions: skipped, season_type=pre\n"


def test_the_run_is_recorded_under_the_agent_the_cron_manifest_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents: list[str] = []
    _wire(monkeypatch, conn=FakeConn(), agents=agents)
    sleeper_cli.cmd_transactions(_args())
    assert agents == ["transactions-sync"]


def test_the_success_line_is_counts_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _wire(monkeypatch, conn=FakeConn(), week=3)
    sleeper_cli.cmd_transactions(_args(quiet=False))
    assert capsys.readouterr().out == "transactions: 8 transactions, 14 moves, weeks 2-3\n"


def test_an_unknown_kind_posts_one_ops_note(monkeypatch: pytest.MonkeyPatch) -> None:
    notifier, _asked = _wire(
        monkeypatch, conn=FakeConn(), report_overrides={"unknown_kinds": Counter({"gift": 2})}
    )
    assert sleeper_cli.cmd_transactions(_args()) == 0
    assert notifier.notes == [
        (
            "transactions weeks 2-3: 2 record(s) of a kind this build does not know (gift); "
            "they are skipped until `KINDS` learns them"
        )
    ]


def test_an_unmatched_roster_posts_one_ops_note(monkeypatch: pytest.MonkeyPatch) -> None:
    notifier, _asked = _wire(
        monkeypatch, conn=FakeConn(), report_overrides={"unmatched_rosters": 1}
    )
    sleeper_cli.cmd_transactions(_args())
    assert notifier.notes == [
        (
            "transactions weeks 2-3: 1 record(s) name a roster with no team row; "
            "run `ug sleeper sync`"
        )
    ]


def test_a_clean_run_says_nothing_in_the_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    notifier, _asked = _wire(monkeypatch, conn=FakeConn())
    sleeper_cli.cmd_transactions(_args())
    assert notifier.notes == []
