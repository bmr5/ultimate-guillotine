import pytest

from ultimate_guillotine.sleeper.models import SleeperLeague, SleeperRoster, SleeperUser
from ultimate_guillotine.sleeper.sync import sync_season, validate_league


def test_validate_rejects_wrong_roster_count() -> None:
    league = SleeperLeague(
        league_id="1389372259260452864",
        name="Ultimate Guillotine League",
        season="2026",
        total_rosters=12,
    )
    with pytest.raises(ValueError, match="expected 18 rosters"):
        validate_league(league, expected_id="1389372259260452864", expected_rosters=18)


def test_validate_rejects_wrong_id() -> None:
    league = SleeperLeague(
        league_id="1", name="Ultimate Guillotine League", season="2026", total_rosters=18
    )
    with pytest.raises(ValueError, match="league id"):
        validate_league(league, expected_id="1389372259260452864", expected_rosters=18)


def test_validate_accepts_matching_league() -> None:
    league = SleeperLeague(
        league_id="1389372259260452864",
        name="Ultimate Guillotine League",
        season="2026",
        total_rosters=18,
    )
    validate_league(league, expected_id="1389372259260452864", expected_rosters=18)


class FakeSyncClient:
    """Fake Sleeper client for testing sync error cases."""

    def __init__(
        self, league: SleeperLeague, users: list[SleeperUser], rosters: list[SleeperRoster]
    ) -> None:
        self._league = league
        self._users = users
        self._rosters = rosters

    def get_league(self, league_id: str) -> SleeperLeague:
        return self._league

    def get_users(self, league_id: str) -> list[SleeperUser]:
        return self._users

    def get_rosters(self, league_id: str) -> list[SleeperRoster]:
        return self._rosters


class FakeSyncConnection:
    """Fake database connection for testing sync error cases."""

    def __init__(self, season_row: tuple[int, int]) -> None:
        self._season_row = season_row
        self._in_transaction = False

    def transaction(self):
        return self

    def __enter__(self):
        self._in_transaction = True
        return self

    def __exit__(self, *args):
        self._in_transaction = False

    def cursor(self):
        return FakeSyncCursor(self._season_row)


class FakeSyncCursor:
    """Fake cursor for testing sync error cases."""

    def __init__(self, season_row: tuple[int, int]) -> None:
        self._season_row = season_row
        self._next_member_id = 100
        self._next_team_id = 200
        self._last_query = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql: str, params=None):
        # Store the SQL query to determine what to return on fetchone().
        self._last_query = sql

    def executemany(self, sql: str, params_seq=()):
        # The holdings upsert batches its rows; nothing here reads them back.
        self._last_query = sql

    def fetchone(self):
        # Return the mocked season row if the query is a season lookup.
        if "select id, expected_rosters from public.seasons" in self._last_query:
            result = self._season_row
            self._season_row = None  # Only return it once
            return result
        # For insert...returning statements, return a mock member ID.
        if "insert into public.members" in self._last_query:
            result = (self._next_member_id,)
            self._next_member_id += 1
            return result
        # The teams upsert returns the new team's id in the same statement.
        if "insert into public.teams" in self._last_query:
            result = (self._next_team_id,)
            self._next_team_id += 1
            return result
        # Every other select (the stored elimination) finds nothing.
        return None


def test_sync_season_raises_on_unknown_owner() -> None:
    """A roster with an unknown owner_id raises ValueError."""
    league = SleeperLeague(
        league_id="1389372259260452864",
        name="Ultimate Guillotine League",
        season="2026",
        total_rosters=2,
    )
    users = [SleeperUser(user_id="user-01", display_name="Member01", metadata={})]
    rosters = [
        SleeperRoster(roster_id=1, owner_id="user-01"),
        SleeperRoster(roster_id=2, owner_id="unknown-user"),  # This user doesn't exist
    ]
    client = FakeSyncClient(league, users, rosters)
    conn = FakeSyncConnection((1, 2))

    with pytest.raises(ValueError, match="roster 2 has no matching user"):
        sync_season(client, conn, year=2026, league_id="1389372259260452864")


def test_sync_season_raises_on_mismatch_count() -> None:
    """A rosters list with fewer entries than expected raises ValueError."""
    league = SleeperLeague(
        league_id="1389372259260452864",
        name="Ultimate Guillotine League",
        season="2026",
        total_rosters=2,
    )
    users = [
        SleeperUser(user_id="user-01", display_name="Member01", metadata={}),
        SleeperUser(user_id="user-02", display_name="Member02", metadata={}),
    ]
    rosters = [SleeperRoster(roster_id=1, owner_id="user-01")]  # Only one roster, but expected 2
    client = FakeSyncClient(league, users, rosters)
    conn = FakeSyncConnection((1, 2))

    with pytest.raises(ValueError, match="expected 2 teams, synced 1"):
        sync_season(client, conn, year=2026, league_id="1389372259260452864")
