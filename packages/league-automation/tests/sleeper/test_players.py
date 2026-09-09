import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx

from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.players import PlayerRepository, load_players, sync_players

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sleeper" / "players_small.json"


def test_load_players_keeps_only_active_skill_positions_and_defenses() -> None:
    players = load_players(json.loads(FIXTURE.read_text()))
    names = {p.full_name for p in players}
    assert "Kansas City Chiefs" in names
    assert all(p.active for p in players)
    assert not any(p.position == "OL" for p in players)
    assert sum(1 for p in players if p.full_name == "Mike Williams") == 2


@respx.mock
def test_get_players_hits_sleeper() -> None:
    respx.get("https://api.sleeper.app/v1/players/nfl").mock(
        return_value=httpx.Response(200, json=json.loads(FIXTURE.read_text()))
    )
    assert "KC" in SleeperClient(httpx.Client()).get_players()


def test_sync_players_upserts_and_records_time(conn) -> None:
    class FakeClient:
        def get_players(self):
            return json.loads(FIXTURE.read_text())

    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    written = sync_players(FakeClient(), conn, now)
    assert written >= 5
    assert sync_players(FakeClient(), conn, now) == written
    repo = PlayerRepository(conn)
    assert repo.last_synced_at() == now
    assert any(p.full_name == "Kansas City Chiefs" for p in repo.all_active())


def test_sync_players_deactivates_players_the_feed_dropped(conn) -> None:
    """A player who retires disappears from Sleeper's dump. Deleting the row
    would orphan every trade that names it, so the row is marked inactive."""
    class FakeClient:
        def __init__(self, raw):
            self._raw = raw

        def get_players(self):
            return self._raw

    raw = json.loads(FIXTURE.read_text())
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    sync_players(FakeClient(raw), conn, now)
    repo = PlayerRepository(conn)
    dropped = repo.all_active()[0].sleeper_player_id

    remaining = {pid: rec for pid, rec in raw.items() if str(pid) != dropped}
    sync_players(FakeClient(remaining), conn, now)

    assert dropped not in {p.sleeper_player_id for p in repo.all_active()}
    with conn.cursor() as cur:
        cur.execute(
            "select active from public.players where sleeper_player_id = %s", (dropped,)
        )
        assert cur.fetchone() == (False,)
