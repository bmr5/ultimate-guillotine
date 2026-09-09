"""``build_roster_index`` resolves trades against the synced ``roster_holdings`` table.

The ten-minute sync keeps the table current, so a 🚨 alert costs no Sleeper call
and still resolves during a Sleeper outage. The live fetch survives only as the
brand-new-season guard: a season with no holdings rows at all.
"""

from datetime import UTC, datetime, timedelta

from ultimate_guillotine.sleeper.models import SleeperRoster
from ultimate_guillotine.trades.resolve import build_roster_index

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


class FakeRosterClient:
    """Counts live Sleeper calls; the point of the table is that there are none."""

    def __init__(self) -> None:
        self.calls = 0

    def get_rosters(self, league_id: str) -> list[SleeperRoster]:
        self.calls += 1
        return [SleeperRoster(roster_id=911, owner_id="u", players=["from-sleeper"])]


def _season_id(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("select id from public.seasons where year = 2026")
        return cur.fetchone()[0]


def _team(conn, display_name: str, roster_id: int) -> tuple[int, int]:
    """One member and their 2026 team; returns ``(member_id, team_id)``."""
    season_id = _season_id(conn)
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.members (display_name) values (%s) returning id",
            (display_name,),
        )
        member_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.teams (season_id, member_id, sleeper_user_id, "
            "sleeper_roster_id, team_name) values (%s, %s, 'u', %s, 'T') returning id",
            (season_id, member_id, roster_id),
        )
        team_id = cur.fetchone()[0]
    return member_id, team_id


def _hold(conn, team_id: int, rows: list[tuple[str, str]], synced_at: datetime) -> None:
    season_id = _season_id(conn)
    with conn.cursor() as cur:
        cur.executemany(
            "insert into public.roster_holdings (season_id, team_id, sleeper_player_id, "
            "slot, synced_at) values (%s, %s, %s, %s, %s)",
            [(season_id, team_id, pid, slot, synced_at) for pid, slot in rows],
        )


def _seed(conn, synced_at: datetime) -> int:
    member_id, team_id = _team(conn, "Index Member", 911)
    _hold(
        conn,
        team_id,
        [("p1", "starter"), ("p2", "bench"), ("p3", "ir"), ("p4", "taxi")],
        synced_at,
    )
    return member_id


def test_index_reads_the_holdings_table_without_calling_sleeper(conn) -> None:
    """Every slot counts: a traded player is as likely to be on IR as starting."""
    member_id = _seed(conn, NOW - timedelta(minutes=5))
    client = FakeRosterClient()
    index = build_roster_index(client, conn, "league", 2026)
    assert client.calls == 0
    assert index.holdings[member_id] == frozenset({"p1", "p2", "p3", "p4"})
    assert index.holds(member_id, "p2") and not index.holds(member_id, "p9")


def test_old_holdings_are_still_used_rather_than_refetched(conn) -> None:
    """A stalled sync is an ops problem, not a reason to resolve against nothing:
    the last good rows beat a live call the registrar may not be able to make."""
    member_id = _seed(conn, NOW - timedelta(hours=7))
    client = FakeRosterClient()
    index = build_roster_index(client, conn, "league", 2026)
    assert client.calls == 0
    assert index.holdings[member_id] == frozenset({"p1", "p2", "p3", "p4"})


def test_a_team_with_no_rows_does_not_drag_the_season_back_to_sleeper(conn) -> None:
    """Partial coverage is not an empty season -- the teams that have rows keep them."""
    held_member = _seed(conn, NOW - timedelta(minutes=5))
    bare_member, _ = _team(conn, "Bare Member", 912)
    client = FakeRosterClient()
    index = build_roster_index(client, conn, "league", 2026)
    assert client.calls == 0
    assert index.holdings[held_member] == frozenset({"p1", "p2", "p3", "p4"})
    assert bare_member not in index.holdings


def test_no_holdings_at_all_falls_back(conn) -> None:
    member_id, _ = _team(conn, "Empty Member", 911)
    client = FakeRosterClient()
    index = build_roster_index(client, conn, "league", 2026)
    assert client.calls == 1 and index.holdings[member_id] == frozenset({"from-sleeper"})


def test_an_unknown_season_gives_an_empty_index(conn) -> None:
    client = FakeRosterClient()
    assert build_roster_index(client, conn, "league", 1999).holdings == {}
