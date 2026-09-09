import json
from pathlib import Path

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


def test_sync_season_is_idempotent(conn) -> None:
    client = FakeSleeperClient()

    first = sync_season(client, conn, year=2026, league_id=LEAGUE_ID)
    assert first == SyncReport(members=18, teams=18, holdings=first.holdings, states=18)
    assert first.holdings > 0

    second = sync_season(client, conn, year=2026, league_id=LEAGUE_ID)
    assert second == first

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
