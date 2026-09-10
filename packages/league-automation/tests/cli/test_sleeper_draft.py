"""What `ug sleeper draft` does around the sync it wraps: the season it looks up, the
agent it records under, and the counts-only line it prints."""

import argparse
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ultimate_guillotine.cli import sleeper as sleeper_cli
from ultimate_guillotine.sleeper.draft import DraftReport

from .test_sleeper_scores import FakeConn, FakeNotifier


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    conn: FakeConn,
    report: DraftReport,
    agents: list[str] | None = None,
) -> list[tuple[str, int]]:
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
    calls: list[tuple[str, int]] = []

    def fake_sync(client, target, league_id, season_id, now):
        calls.append((league_id, season_id))
        return report

    monkeypatch.setattr(sleeper_cli, "sync_draft", fake_sync)

    def fake_runner(deps, agent, now, action):
        if agents is not None:
            agents.append(agent)
        return action(1)

    monkeypatch.setattr(sleeper_cli, "run_scheduled_with_notes", fake_runner)
    return calls


def test_draft_help_exists() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ultimate_guillotine.cli.main", "sleeper", "draft", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--quiet" in result.stdout


def test_the_season_is_the_leagues_own_year(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn(season_row=(4,))
    calls = _wire(monkeypatch, conn=conn, report=DraftReport(picks=162, status="complete"))

    assert sleeper_cli.cmd_draft(argparse.Namespace(quiet=True)) == 0
    assert calls == [("league-1", 4)]
    assert conn.queries[0][1] == (sleeper_cli.SYNC_YEAR,)


def test_the_run_is_recorded_under_the_agent_the_cron_manifest_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents: list[str] = []
    _wire(
        monkeypatch,
        conn=FakeConn(),
        report=DraftReport(picks=162, status="complete"),
        agents=agents,
    )
    sleeper_cli.cmd_draft(argparse.Namespace(quiet=True))
    assert agents == ["draft-sync"]


def test_the_success_line_is_counts_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _wire(monkeypatch, conn=FakeConn(), report=DraftReport(picks=162, status="complete"))
    sleeper_cli.cmd_draft(argparse.Namespace(quiet=False))
    assert capsys.readouterr().out == "draft: 162 picks\n"


def test_a_draft_still_running_says_so_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _wire(monkeypatch, conn=FakeConn(), report=DraftReport(picks=0, status="drafting"))
    assert sleeper_cli.cmd_draft(argparse.Namespace(quiet=False)) == 0
    assert capsys.readouterr().out == "draft: skipped, status=drafting\n"


def test_quiet_prints_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _wire(monkeypatch, conn=FakeConn(), report=DraftReport(picks=0, status="drafting"))
    sleeper_cli.cmd_draft(argparse.Namespace(quiet=True))
    assert capsys.readouterr().out == ""
