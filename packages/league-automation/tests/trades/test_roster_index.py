"""``build_roster_index`` resolves trades against the synced ``roster_holdings`` table.

The ten-minute sync keeps the table current, so a 🚨 alert costs no Sleeper call
and still resolves during a Sleeper outage. The live fetch survives as the
freshness guard: a season with no holdings rows at all, or a sync heartbeat
(``seasons.league_synced_at``) missing or older than ``HOLDINGS_MAX_AGE``, falls
back to one live fetch.
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


def _heartbeat(conn, synced_at: datetime | None) -> None:
    """Stamp the 2026 season the way every sync pass does."""
    with conn.cursor() as cur:
        cur.execute(
            "update public.seasons set league_synced_at = %s where year = 2026", (synced_at,)
        )


def _seed(conn, synced_at: datetime, *, rows_changed_at: datetime | None = None) -> int:
    """A synced roster: ``synced_at`` is the sync's heartbeat, ``rows_changed_at`` when
    the holdings themselves last changed -- the same moment unless a test says not."""
    member_id, team_id = _team(conn, "Index Member", 911)
    _hold(
        conn,
        team_id,
        [("p1", "starter"), ("p2", "bench"), ("p3", "ir"), ("p4", "taxi")],
        synced_at if rows_changed_at is None else rows_changed_at,
    )
    _heartbeat(conn, synced_at)
    return member_id


def test_index_reads_the_holdings_table_without_calling_sleeper(conn) -> None:
    """Every slot counts: a traded player is as likely to be on IR as starting."""
    member_id = _seed(conn, NOW - timedelta(minutes=5))
    client = FakeRosterClient()
    index = build_roster_index(client, conn, "league", 2026, now=NOW)
    assert client.calls == 0
    assert index.holdings[member_id] == frozenset({"p1", "p2", "p3", "p4"})
    assert index.holds(member_id, "p2") and not index.holds(member_id, "p9")


def test_stale_holdings_fall_back_to_one_sleeper_call(conn) -> None:
    """Seven hours past a six-hour ceiling: the rows have moved on, so the
    registrar pays for one live fetch rather than resolving against them."""
    member_id = _seed(conn, NOW - timedelta(hours=7))
    client = FakeRosterClient()
    index = build_roster_index(client, conn, "league", 2026, now=NOW)
    assert client.calls == 1
    assert index.holdings[member_id] == frozenset({"from-sleeper"})


def test_a_roster_unchanged_for_days_under_a_fresh_sync_reads_the_table(conn) -> None:
    """A holding's ``synced_at`` is when it last changed, not when it was last checked.

    The sync leaves an unchanged holding alone -- every rewrite was a Realtime message
    to every open board -- so a quiet roster's rows are days old while the sync that
    confirmed them ran minutes ago. ``seasons.league_synced_at`` is that confirmation.
    """
    member_id = _seed(conn, NOW - timedelta(minutes=5), rows_changed_at=NOW - timedelta(days=3))
    client = FakeRosterClient()
    index = build_roster_index(client, conn, "league", 2026, now=NOW)
    assert client.calls == 0
    assert index.holdings[member_id] == frozenset({"p1", "p2", "p3", "p4"})


def test_a_stalled_sync_falls_back_however_recent_the_last_change(conn) -> None:
    member_id = _seed(conn, NOW - timedelta(hours=7), rows_changed_at=NOW - timedelta(minutes=5))
    client = FakeRosterClient()
    index = build_roster_index(client, conn, "league", 2026, now=NOW)
    assert client.calls == 1
    assert index.holdings[member_id] == frozenset({"from-sleeper"})


def test_holdings_with_no_sync_heartbeat_fall_back(conn) -> None:
    """Rows nobody vouches for are an unknown age, not a fresh one."""
    _seed(conn, NOW - timedelta(minutes=5))
    _heartbeat(conn, None)
    client = FakeRosterClient()
    build_roster_index(client, conn, "league", 2026, now=NOW)
    assert client.calls == 1


def test_a_team_with_no_rows_does_not_drag_the_season_back_to_sleeper(conn) -> None:
    """Partial coverage is not staleness -- a fresh table is used as it stands."""
    held_member = _seed(conn, NOW - timedelta(minutes=5))
    bare_member, _ = _team(conn, "Bare Member", 912)
    client = FakeRosterClient()
    index = build_roster_index(client, conn, "league", 2026, now=NOW)
    assert client.calls == 0
    assert index.holdings[held_member] == frozenset({"p1", "p2", "p3", "p4"})
    assert bare_member not in index.holdings


def test_no_holdings_at_all_falls_back(conn) -> None:
    member_id, _ = _team(conn, "Empty Member", 911)
    client = FakeRosterClient()
    index = build_roster_index(client, conn, "league", 2026, now=NOW)
    assert client.calls == 1 and index.holdings[member_id] == frozenset({"from-sleeper"})


def test_an_unknown_season_gives_an_empty_index(conn) -> None:
    client = FakeRosterClient()
    assert build_roster_index(client, conn, "league", 1999, now=NOW).holdings == {}
    assert client.calls == 1
