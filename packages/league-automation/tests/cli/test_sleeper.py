"""What week `ug sleeper sync` stamps an inferred elimination with.

`NflState.week` is scoped by `season_type`: preseason and postseason restart the
count from 1, so the number alone does not say which week of the season it is.
These tests pin the gate rather than the plumbing, so the whole command is faked
down to the one argument under test.
"""

import argparse
from types import SimpleNamespace

import pytest

from ultimate_guillotine.cli import sleeper as sleeper_cli


def _week_passed_to_sync(monkeypatch: pytest.MonkeyPatch, season_type: str, week: int) -> object:
    """Run `cmd_sync` against a faked Sleeper and database; return its `week` argument."""
    seen: dict[str, object] = {}

    def fake_sync(client, conn, year, league_id, week=None):
        seen["week"] = week
        return SimpleNamespace(members=18, teams=18, holdings=9, states=18)

    monkeypatch.setattr(
        sleeper_cli,
        "build_deps",
        lambda: SimpleNamespace(
            conn=object(),
            notifier=SimpleNamespace(ops=lambda text: True),
            settings=SimpleNamespace(sleeper_league_id="league-id"),
        ),
    )
    monkeypatch.setattr(sleeper_cli.httpx, "Client", lambda: object())
    monkeypatch.setattr(sleeper_cli, "SleeperClient", lambda http: object())
    monkeypatch.setattr(
        sleeper_cli,
        "current_week",
        lambda client, conn, now: SimpleNamespace(season_type=season_type, week=week),
    )
    monkeypatch.setattr(sleeper_cli, "sync_season", fake_sync)
    monkeypatch.setattr(
        sleeper_cli, "run_scheduled_with_notes", lambda deps, agent, now, action: action(1)
    )

    assert sleeper_cli.cmd_sync(argparse.Namespace(quiet=True)) == 0
    return seen["week"]


def test_sync_stamps_eliminations_with_the_regular_season_week(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _week_passed_to_sync(monkeypatch, "regular", 3) == 3


def test_a_preseason_week_never_dates_an_elimination(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preseason week 2 is not week 2 of the season, and neither is playoff week 2.

    Passing either through would stamp `eliminated_week = 2` on a roster tagged
    out of season, which reads later as an elimination in September.
    """
    assert _week_passed_to_sync(monkeypatch, "pre", 2) is None
    assert _week_passed_to_sync(monkeypatch, "post", 2) is None
