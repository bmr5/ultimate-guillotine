"""Shared Sleeper fixtures: the fake client and the league/roster payloads.

Every sync-shaped test needs the same three things -- the 2026 league, its 18
users, and its 18 rosters -- served by something that looks like
``SleeperClient``. They live here rather than in one test module so the later
projection tests reuse them instead of copying them.

``rosters`` hands back a *fresh* parse of the fixture on every request, because
tests mutate it (dropping a player, blanking a starter slot) to exercise what a
second sync does with a changed roster.
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from ultimate_guillotine.sleeper.models import (
    SleeperDraft,
    SleeperLeague,
    SleeperRoster,
    SleeperUser,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sleeper"

#: The real league's id, which the fixtures and every sync call share.
LEAGUE_ID = "1389372259260452864"


def load_fixture(name: str) -> list | dict:
    """Parse one Sleeper JSON fixture."""
    return json.loads((FIXTURES / name).read_text())


class FakeClient:
    """Stands in for ``SleeperClient``, serving the JSON fixtures.

    ``rosters`` is the raw payload list, so a test can mutate it (drop a player,
    blank a starter slot) and hand the same instance back for a second sync.
    """

    def __init__(self, rosters: list[dict] | None = None) -> None:
        self._league = SleeperLeague.model_validate(load_fixture("league_2026.json"))
        self._users = [SleeperUser.model_validate(item) for item in load_fixture("users_2026.json")]
        self._roster_payload = load_fixture("rosters_2026.json") if rosters is None else rosters

    def get_league(self, league_id: str) -> SleeperLeague:
        return self._league

    def get_users(self, league_id: str) -> list[SleeperUser]:
        return self._users

    def get_rosters(self, league_id: str) -> list[SleeperRoster]:
        return [SleeperRoster.model_validate(item) for item in self._roster_payload]

    def get_draft(self, draft_id: str) -> SleeperDraft:
        return SleeperDraft.model_validate(load_fixture("draft_2026.json"))

    def get_draft_picks(self, draft_id: str) -> list[dict]:
        return load_fixture("draft_picks_2026.json")

    def get_transactions(self, league_id: str, week: int) -> list[dict]:
        return load_fixture("transactions_2026_w1.json") if week == 1 else []


@pytest.fixture
def rosters() -> list[dict]:
    """A fresh, mutable copy of the 18-roster payload."""
    return load_fixture("rosters_2026.json")


@pytest.fixture
def sleeper_client(rosters: list[dict]) -> FakeClient:
    """A ``FakeClient`` over the mutable ``rosters`` payload."""
    return FakeClient(rosters)


@pytest.fixture
def season_id(conn) -> int:
    """The id of the 2026 season row the migrations seeded."""
    with conn.cursor() as cur:
        cur.execute("select id from public.seasons where year = 2026")
        row = cur.fetchone()
    assert row is not None, "no 2026 season row"
    return row[0]


@pytest.fixture
def team_id(conn, season_id: int) -> Callable[[int], int]:
    """``team_id(roster_id)`` -- the ``public.teams`` id a sync gave that roster."""

    def lookup(roster_id: int) -> int:
        with conn.cursor() as cur:
            cur.execute(
                "select id from public.teams where season_id = %s and sleeper_roster_id = %s",
                (season_id, roster_id),
            )
            row = cur.fetchone()
        assert row is not None, f"roster {roster_id} has no team row"
        return row[0]

    return lookup
