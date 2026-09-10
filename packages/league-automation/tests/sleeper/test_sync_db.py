import json
from dataclasses import replace
from pathlib import Path

from ultimate_guillotine.data.repositories import MemberAliasRepository
from ultimate_guillotine.sleeper.models import SleeperLeague, SleeperRoster, SleeperUser
from ultimate_guillotine.sleeper.sync import SyncReport, sync_season

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sleeper"
LEAGUE_ID = "1389372259260452864"


def _load(name: str) -> list | dict:
    return json.loads((FIXTURES / name).read_text())


class FakeSleeperClient:
    """Stands in for ``SleeperClient``, serving the JSON fixtures."""

    def __init__(self) -> None:
        self._league = SleeperLeague.model_validate(_load("league_2026.json"))
        self._users = [SleeperUser.model_validate(item) for item in _load("users_2026.json")]
        self._rosters = [SleeperRoster.model_validate(item) for item in _load("rosters_2026.json")]

    def get_league(self, league_id: str) -> SleeperLeague:
        assert league_id == LEAGUE_ID
        return self._league

    def get_users(self, league_id: str) -> list[SleeperUser]:
        assert league_id == LEAGUE_ID
        return self._users

    def get_rosters(self, league_id: str) -> list[SleeperRoster]:
        assert league_id == LEAGUE_ID
        return self._rosters


def _holdings_in_fixture() -> int:
    """Every distinct player id the roster fixtures name, which is one holding each.

    `classify_holdings` writes one row per id, whichever list it appeared in, and
    skips Sleeper's `"0"` placeholder for an empty starter slot.
    """
    return sum(
        len(
            {
                player_id
                for key in ("starters", "players", "reserve", "taxi")
                for player_id in (roster.get(key) or [])
                if player_id and player_id != "0"
            }
        )
        for roster in _load("rosters_2026.json")
    )


def test_sync_season_is_idempotent(conn) -> None:
    client = FakeSleeperClient()

    expected_holdings = _holdings_in_fixture()
    assert expected_holdings > 0, "the roster fixtures name no players"

    first = sync_season(client, conn, year=2026, league_id=LEAGUE_ID)
    assert first == SyncReport(
        members=18, teams=18, holdings=expected_holdings, states=18, frozen=1
    )

    # The rows are idempotent, and `frozen` is honest about that rather than in
    # spite of it: it counts the final-roster snapshots *this* run wrote, and the
    # one eliminated team in the fixture was already frozen by the first pass.
    second = sync_season(client, conn, year=2026, league_id=LEAGUE_ID)
    assert second == replace(first, frozen=0)

    with conn.cursor() as cur:
        cur.execute("select count(*) from public.members")
        assert cur.fetchone()[0] == 18

        cur.execute(
            """
            select count(*) from public.teams t
            join public.seasons s on s.id = t.season_id
            where s.year = 2026
            """
        )
        assert cur.fetchone()[0] == 18

        cur.execute(
            """
            select team_name from public.teams t
            join public.members m on m.id = t.member_id
            where m.display_name = 'Member01'
            """
        )
        assert cur.fetchone()[0] == "The Guillotine Blades"


def test_sync_leaves_a_former_member_alone(conn) -> None:
    """A departed manager's profile is not Sleeper's to reconcile.

    `sync_season` upserts `public.members` on `display_name` and never deletes, so the only
    thing standing between a hand-written profile and being overwritten (or, worse, having
    its `sleeper_display_name` filled in from somebody else's account) is that the key it
    was given cannot be a Sleeper username. `former:` is that guarantee, and this is the
    test that says so.
    """
    repo = MemberAliasRepository(conn)
    created, aliases = repo.upsert_former("Sentinel Former", ["Sentinel Nick"])
    assert (created, aliases) == (True, 2)

    sync_season(FakeSleeperClient(), conn, year=2026, league_id=LEAGUE_ID)

    with conn.cursor() as cur:
        cur.execute(
            "select nickname, sleeper_display_name from public.members where display_name = %s",
            ("former:sentinel-former",),
        )
        assert cur.fetchone() == ("Sentinel Former", None)
        # And the sync did not adopt the row into the league either: no team points at it.
        cur.execute(
            """
            select count(*) from public.teams t
            join public.members m on m.id = t.member_id
            where m.display_name = 'former:sentinel-former'
            """
        )
        assert cur.fetchone()[0] == 0
        cur.execute("select count(*) from public.members")
        # The league's 18, plus the one profile that is not part of it.
        assert cur.fetchone()[0] == 19
