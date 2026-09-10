"""What `ug sleeper scores` does around the sync it wraps.

The sync itself is covered against a real table in `tests/sleeper/test_scores.py`.
The point under test here is everything around it: which week it asks for, which
season row it looks up, that the off-season is a no-op rather than a failure, and
that the run is recorded under the agent the health check and the cron manifest
both name.
"""

import argparse
import subprocess
import sys
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Self

import pytest

from ultimate_guillotine.cli import sleeper as sleeper_cli


@dataclass
class Call:
    league_id: str
    season_id: int
    week: int


class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self._conn = conn

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._conn.queries.append((sql, params))

    def fetchone(self) -> tuple | None:
        return self._conn.season_row


class FakeConn:
    """Records the season lookup. The sync is faked, so nothing else touches it."""

    def __init__(self, season_row: tuple | None = (4,)) -> None:
        self.season_row = season_row
        self.queries: list[tuple[str, tuple]] = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)


class FakeNotifier:
    def __init__(self) -> None:
        self.notes: list[str] = []

    def ops(self, text: str) -> bool:
        self.notes.append(text)
        return True


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    conn: FakeConn,
    season_type: str = "regular",
    season: int = 2026,
    week: int = 3,
    unmatched: int = 0,
    agents: list[str] | None = None,
) -> tuple[FakeNotifier, list[Call]]:
    notifier = FakeNotifier()
    monkeypatch.setattr(
        sleeper_cli,
        "build_deps",
        lambda: SimpleNamespace(
            conn=conn,
            notifier=notifier,
            settings=SimpleNamespace(sleeper_league_id="league-1"),
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

    calls: list[Call] = []

    def fake_sync(client, target, league_id, season_id, requested_week, now):
        calls.append(Call(league_id, season_id, requested_week))
        return SimpleNamespace(teams=18, week=requested_week, unmatched_rosters=unmatched)

    monkeypatch.setattr(sleeper_cli, "sync_scores", fake_sync)

    def fake_runner(deps, agent, now, action):
        if agents is not None:
            agents.append(agent)
        return action(1)

    monkeypatch.setattr(sleeper_cli, "run_scheduled_with_notes", fake_runner)
    return notifier, calls


def _args(**overrides) -> argparse.Namespace:
    return argparse.Namespace(**{"week": None, "quiet": True, **overrides})


def test_scores_help_lists_the_week_override() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ultimate_guillotine.cli.main", "sleeper", "scores", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--week" in result.stdout


def test_the_week_defaults_to_the_state_week(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn()
    _notifier, calls = _wire(monkeypatch, conn=conn, week=5)

    assert sleeper_cli.cmd_scores(_args()) == 0
    assert calls == [Call("league-1", 4, 5)]


def test_an_explicit_week_overrides_the_state(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn()
    _notifier, calls = _wire(monkeypatch, conn=conn, week=5)

    sleeper_cli.cmd_scores(_args(week=2))
    assert calls == [Call("league-1", 4, 2)]


def test_the_season_row_is_looked_up_by_the_state_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`SYNC_YEAR` is this league's season; the year being played is whatever `nfl_state`
    says, and the two part company every January."""
    conn = FakeConn()
    _wire(monkeypatch, conn=conn, season=2027)

    sleeper_cli.cmd_scores(_args())
    assert conn.queries[0][1] == (2027,)


def test_an_empty_scoring_settings_column_does_not_block_a_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The season lookup here is deliberately not `_season_row`: a matchup row carries
    Sleeper's own points, so the league's scoring settings are not a precondition for
    reading a score, and inheriting that refusal would take live scores off the board
    over a column they never touch. The fake season row carries an id and nothing else."""
    conn = FakeConn(season_row=(4,))
    _notifier, calls = _wire(monkeypatch, conn=conn)

    assert sleeper_cli.cmd_scores(_args()) == 0
    assert calls[0].season_id == 4


def test_a_missing_season_row_is_an_error_not_a_silent_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConn(season_row=None)
    _wire(monkeypatch, conn=conn, season=2031)

    with pytest.raises(ValueError, match="no season row for year 2031"):
        sleeper_cli.cmd_scores(_args())


def test_a_preseason_run_is_a_clean_no_op_not_a_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """`week` restarts inside each `season_type`, so a preseason week 2 written as week 2
    would sit under the live board's own week and read as this week's score. Refusing is
    not failing: the job stays green through the whole off-season."""
    conn = FakeConn()
    _notifier, calls = _wire(monkeypatch, conn=conn, season_type="pre")

    assert sleeper_cli.cmd_scores(_args()) == 0
    assert calls == []
    assert capsys.readouterr().out == ""


def test_the_run_is_recorded_under_the_agent_the_cron_manifest_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`scores-sync` is what `hermes/guillotine/cron.yaml` records and what
    `ug ops health` reads back; a rename here would silently stop the health check
    watching this job at all."""
    agents: list[str] = []
    _wire(monkeypatch, conn=FakeConn(), agents=agents)

    sleeper_cli.cmd_scores(_args())
    assert agents == ["scores-sync"]


def test_the_success_line_is_counts_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _wire(monkeypatch, conn=FakeConn(), week=6)

    sleeper_cli.cmd_scores(_args(quiet=False))
    assert capsys.readouterr().out == "scores: 18 teams, week 6\n"


def test_an_unmatched_roster_posts_one_ops_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`public.teams` behind the league is a `ug sleeper sync` away from fixed and no
    reason for the other teams to lose their scores, so it is a note, not a failure."""
    notifier, _calls = _wire(monkeypatch, conn=FakeConn(), week=6, unmatched=2)

    assert sleeper_cli.cmd_scores(_args()) == 0
    assert notifier.notes == [
        "scores week 6: 2 Sleeper roster(s) match no team row; run `ug sleeper sync`"
    ]


def test_a_clean_run_says_nothing_in_the_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This fires once a minute through a game window. A note per run is a wall of
    identical lines nobody reads."""
    notifier, _calls = _wire(monkeypatch, conn=FakeConn())

    sleeper_cli.cmd_scores(_args())
    assert notifier.notes == []
