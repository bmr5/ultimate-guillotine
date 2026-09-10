import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.players import (
    KNOWN_INJURY_STATUSES,
    PlayerRepository,
    load_players,
    load_players_with_notes,
    sync_players,
)

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
    report = sync_players(FakeClient(), conn, now)
    assert report.written >= 5
    assert sync_players(FakeClient(), conn, now) == report
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
        cur.execute("select active from public.players where sleeper_player_id = %s", (dropped,))
        assert cur.fetchone() == (False,)


def test_sync_players_refuses_an_empty_feed(conn) -> None:
    """A thin 200 from Sleeper must not flip the whole directory inactive."""

    class FakeClient:
        def __init__(self, raw):
            self._raw = raw

        def get_players(self):
            return self._raw

    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    sync_players(FakeClient(json.loads(FIXTURE.read_text())), conn, now)
    before = {p.sleeper_player_id for p in PlayerRepository(conn).all_active()}
    with pytest.raises(RuntimeError):
        sync_players(FakeClient({}), conn, now)
    assert {p.sleeper_player_id for p in PlayerRepository(conn).all_active()} == before


def test_load_players_carries_sleeper_injury_status() -> None:
    """Ben's addendum: a starter who is out and a starter Sleeper simply has no
    number for look identical on the board unless the directory says which is
    which. Sleeper's flag is carried verbatim; an absent or empty one is null,
    never the empty string the feed occasionally emits."""
    by_id = {p.sleeper_player_id: p for p in load_players(json.loads(FIXTURE.read_text()))}
    assert by_id["7777"].injury_status == "Out"
    assert by_id["4046"].injury_status == "Questionable"
    assert by_id["1234"].injury_status is None
    assert by_id["6666"].injury_status is None


def test_load_players_reads_an_unknown_status_as_no_flag_and_counts_it() -> None:
    """Sleeper can add a tenth status on any Tuesday. It must not reach a card as an
    unreadable tag, and it must not take a player out of a lineup on a string nobody
    has read -- but it cannot go by unremarked either, so it is counted."""
    load = load_players_with_notes(json.loads(FIXTURE.read_text()))
    by_id = {p.sleeper_player_id: p for p in load.players}
    assert "Limited" not in KNOWN_INJURY_STATUSES
    assert by_id["2468"].injury_status is None
    assert load.unknown_statuses == {"Limited": 1}
    # The nine Sleeper actually emits are untouched by the same pass.
    assert by_id["7777"].injury_status == "Out"


def test_sync_players_writes_and_clears_injury_status(conn) -> None:
    """The flag is a current-state fact, so it has to come *off* a player who
    recovers as readily as it goes on -- an upsert that only ever set it would
    leave last month's `Out` on a healthy starter forever."""

    class FakeClient:
        def __init__(self, raw):
            self._raw = raw

        def get_players(self):
            return self._raw

    raw = json.loads(FIXTURE.read_text())
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    sync_players(FakeClient(raw), conn, now)

    def status(pid: str) -> str | None:
        with conn.cursor() as cur:
            cur.execute(
                "select injury_status from public.players where sleeper_player_id = %s", (pid,)
            )
            return cur.fetchone()[0]

    assert status("7777") == "Out"
    assert status("4046") == "Questionable"
    assert status("1234") is None

    recovered = json.loads(FIXTURE.read_text())
    del recovered["7777"]["injury_status"]
    sync_players(FakeClient(recovered), conn, now)
    assert status("7777") is None

    assert {p.sleeper_player_id: p.injury_status for p in PlayerRepository(conn).all_active()}[
        "4046"
    ] == "Questionable"


def test_sync_players_survives_a_status_it_has_never_seen(conn) -> None:
    """The failure this replaces: a tenth Sleeper value hit a check constraint and
    aborted the whole transaction, so the directory froze on the last good rows --
    over one string, on a job that had just read 12,000 records correctly. Now the
    run writes everything, stores no flag for that player, and reports the count so
    ops can go and read about it."""

    class FakeClient:
        def __init__(self, raw):
            self._raw = raw

        def get_players(self):
            return self._raw

    raw = json.loads(FIXTURE.read_text())
    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    report = sync_players(FakeClient(raw), conn, now)

    assert report.unknown_statuses == 1
    assert report.unknown_values == ("Limited",)
    # Everyone was still written, and the unreadable flag simply is not on the row.
    ids = {p.sleeper_player_id: p.injury_status for p in PlayerRepository(conn).all_active()}
    assert ids["2468"] is None
    assert ids["7777"] == "Out"

    # And an ordinary week says nothing at all: the count is an exception, not a fixture.
    ordinary = json.loads(FIXTURE.read_text())
    del ordinary["2468"]["injury_status"]
    quiet = sync_players(FakeClient(ordinary), conn, now)
    assert quiet.unknown_statuses == 0
    assert quiet.unknown_values == ()
