from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

import pytest
from psycopg.types.json import Jsonb

from tests.agent.fixture import (
    ASKER_MEMBER_ID,
    ELIMINATED_MEMBER_ID,
    FIXTURE_SYNCED_AT,
    fixture_snapshot,
)
from ultimate_guillotine.agent.tools.snapshot import (
    COVERAGE_GATE,
    LAST_REGULAR_WEEK,
    LeagueSnapshot,
    SnapshotRepository,
    SnapshotUnavailable,
)

#: A season no sync will ever have written, so these tests never collide with the
#: real rows a developer's local stack already carries.
SENTINEL_SEASON = 2099
SEEDED_AT = datetime(2099, 10, 8, 15, 0, tzinfo=UTC)
#: Every query :meth:`SnapshotRepository.load` runs: nfl_state, the season id, the
#: teams, the team-week rows, the holdings, the player projections. Pinned so that
#: a later "just one more lookup" inside the per-team loop shows up as a failure
#: rather than as an N+1 nobody notices until the league has eighteen teams.
LOAD_QUERY_COUNT = 6


def test_fixture_has_eighteen_teams_with_a_known_pressure_order() -> None:
    snapshot = fixture_snapshot()
    assert len(snapshot.teams) == 18
    totals = [team.projected_now for team in snapshot.teams]
    assert totals == sorted(totals, reverse=True)
    assert snapshot.teams[ELIMINATED_MEMBER_ID - 1].is_eliminated
    assert snapshot.coverage_ok()


def test_starters_and_bench_split_on_the_slot_column() -> None:
    team = fixture_snapshot().team_for_member(ASKER_MEMBER_ID)
    assert len(team.starters()) == 8 and len(team.bench()) == 6
    assert all(h.slot == "starter" for h in team.starters())
    assert all(h.slot == "bench" for h in team.bench())


def test_below_the_gate_every_projection_is_withheld() -> None:
    snapshot = fixture_snapshot(coverage_pct=Decimal("90.00"))
    assert not snapshot.coverage_ok()
    assert all(team.is_provisional for team in snapshot.teams)
    assert all(team.projected_now is None for team in snapshot.teams)
    # The counting fallback only gets exercised if the holdings go dark too.
    assert all(not h.projected_points for team in snapshot.teams for h in team.holdings)
    assert COVERAGE_GATE == 95.0


def test_the_fixture_league_is_all_decimals() -> None:
    team = fixture_snapshot().team_for_member(ASKER_MEMBER_ID)
    assert isinstance(team.projected_now, Decimal)
    assert isinstance(team.coverage_pct, Decimal)
    assert isinstance(team.starters()[0].projected_now, Decimal)
    assert isinstance(team.faab_remaining, int)


def _bench_points(team, position: str) -> Decimal:
    return sum((h.projected_now for h in team.bench() if h.position == position), Decimal(0))


def test_the_fixture_rosters_are_not_eighteen_copies_of_one_team() -> None:
    """Some teams are RB-rich and WR-poor; their mirror image is what a trade fits."""
    teams = fixture_snapshot().teams
    shapes = {tuple(h.position for h in team.holdings) for team in teams}
    assert len(shapes) > 1, "every roster has the identical positional shape"
    complementary = [
        (a.member_id, b.member_id)
        for a in teams
        for b in teams
        if a.member_id != b.member_id
        and _bench_points(a, "RB") > _bench_points(b, "RB")
        and _bench_points(a, "WR") < _bench_points(b, "WR")
    ]
    assert complementary, "no pair of teams is long what the other is short"


def test_the_tilt_does_not_disturb_the_pressure_order() -> None:
    totals = [team.projected_now for team in fixture_snapshot().teams]
    gaps = [a - b for a, b in pairwise(totals)]
    assert all(gap > 0 for gap in gaps)


def test_staleness_is_measured_from_the_oldest_component() -> None:
    """A fresh projection run must not vouch for a roster sync that stalled."""
    stalled = FIXTURE_SYNCED_AT - timedelta(hours=2)
    snapshot = fixture_snapshot(oldest_synced_at=stalled)
    now = FIXTURE_SYNCED_AT + timedelta(minutes=10)
    # The newest stamp is still what a "last updated" line would show...
    assert snapshot.synced_at == FIXTURE_SYNCED_AT
    # ...but the advice is gated on the oldest.
    assert snapshot.is_stale(now)
    assert snapshot.age(now) == timedelta(hours=2, minutes=10)


def test_staleness_when_every_component_synced_together() -> None:
    snapshot = fixture_snapshot()
    fresh = FIXTURE_SYNCED_AT + timedelta(minutes=10)
    stale = FIXTURE_SYNCED_AT + timedelta(minutes=31)
    assert not snapshot.is_stale(fresh)
    assert snapshot.is_stale(stale)
    assert snapshot.age(stale) == timedelta(minutes=31)


def test_lookups_by_member_and_display_name() -> None:
    snapshot = fixture_snapshot()
    assert snapshot.team_for_member(ASKER_MEMBER_ID).display_name == "Member05"
    assert snapshot.team_by_name("Member05").member_id == ASKER_MEMBER_ID
    assert snapshot.team_by_name("Nobody") is None
    assert snapshot.player_names()["p05s0"] == "Starter 05-0"
    assert len(snapshot.member_names()) == 18


def test_an_ambiguous_name_matches_nobody() -> None:
    """Two managers under one name is a question to ask, not a coin to flip."""
    snapshot = fixture_snapshot()
    first, second = snapshot.teams[0], snapshot.teams[1]
    clash = replace(second, member_label=first.member_label)
    ambiguous = replace(snapshot, teams=(first, clash, *snapshot.teams[2:]))
    assert ambiguous.team_by_name(first.member_label) is None
    # The unambiguous label still resolves, so this is not a blanket refusal.
    assert ambiguous.team_by_name("Member03").member_id == 3


def test_a_horizon_carries_a_projection_for_every_week_in_it() -> None:
    snapshot = fixture_snapshot(horizon_weeks=2)
    assert snapshot.weeks == (6, 7)
    holding = snapshot.team_for_member(ASKER_MEMBER_ID).starters()[0]
    assert sorted(holding.projected_points) == [6, 7]
    assert holding.projected_now == holding.projected_points[6]
    assert holding.projected_for(7) == holding.projected_points[6] - Decimal("0.5")
    assert holding.projected_for(9) is None


def test_the_fixture_horizon_stops_at_the_last_regular_week() -> None:
    snapshot = fixture_snapshot(week=LAST_REGULAR_WEEK, horizon_weeks=3)
    assert snapshot.weeks == (LAST_REGULAR_WEEK,)


# --- database-backed ---------------------------------------------------------


def test_load_without_an_nfl_state_row_is_unavailable(conn) -> None:
    with conn.cursor() as cur:
        # Rolled back with the fixture's transaction; a developer who has run the
        # state sync locally should still see the no-row branch under test.
        cur.execute("delete from public.nfl_state")
    with pytest.raises(SnapshotUnavailable, match="nfl_state"):
        SnapshotRepository(conn).load()


def test_load_outside_the_regular_season_is_unavailable(conn) -> None:
    _seed_minimal_league(conn)
    with conn.cursor() as cur:
        cur.execute("update public.nfl_state set season_type = 'pre' where id = 1")
    with pytest.raises(SnapshotUnavailable, match="season_type"):
        SnapshotRepository(conn).load()


def test_load_without_a_seasons_row_is_unavailable(conn) -> None:
    _seed_nfl_state(conn)
    with pytest.raises(SnapshotUnavailable, match="seasons"):
        SnapshotRepository(conn).load()


def test_load_with_no_teams_for_the_season_is_unavailable(conn) -> None:
    _seed_nfl_state(conn)
    _seed_season(conn)
    with pytest.raises(SnapshotUnavailable, match="no teams"):
        SnapshotRepository(conn).load()


def test_load_reads_one_week_of_the_data_layer(conn) -> None:
    _season_id, _member_id, team_id = _seed_minimal_league(conn)
    snapshot = SnapshotRepository(conn).load()
    assert snapshot.season == SENTINEL_SEASON and snapshot.week == 6
    assert snapshot.weeks == (6,)
    assert len(snapshot.teams) == 1
    team = _seeded_team(snapshot, team_id)
    assert team.display_name == "Member01" and team.faab_remaining == 700
    assert [h.sleeper_player_id for h in team.starters()] == ["px1"]
    assert team.starters()[0].projected_now == Decimal("18.50")
    assert team.starters()[0].player_name == "Player X1"
    assert team.bench()[0].sleeper_player_id == "px2"
    assert team.bench()[0].projected_now == Decimal("9.25")
    assert snapshot.synced_at == SEEDED_AT and snapshot.oldest_synced_at == SEEDED_AT


def test_the_data_layer_answers_in_decimals(conn) -> None:
    """``numeric`` in, ``Decimal`` out -- no float rounds the league's arithmetic."""
    _season_id, _member_id, team_id = _seed_minimal_league(conn)
    team = _seeded_team(SnapshotRepository(conn).load(), team_id)
    assert isinstance(team.projected_now, Decimal)
    assert team.projected_now == Decimal("18.50")
    assert isinstance(team.coverage_pct, Decimal)
    assert isinstance(team.starters()[0].projected_now, Decimal)
    assert isinstance(team.faab_remaining, int)


def test_a_two_week_horizon_reads_both_weeks(conn) -> None:
    _season_id, _member_id, team_id = _seed_minimal_league(conn, weeks=(6, 7))
    snapshot = SnapshotRepository(conn).load(horizon_weeks=2)
    assert snapshot.weeks == (6, 7)
    team = _seeded_team(snapshot, team_id)
    assert dict(team.starters()[0].projected_points) == {
        6: Decimal("18.50"),
        7: Decimal("17.00"),
    }
    assert dict(team.projected_points) == {6: Decimal("18.50"), 7: Decimal("17.00")}
    # The default horizon still reads this week alone, off the same rows.
    assert SnapshotRepository(conn).load().weeks == (6,)


def test_the_horizon_stops_at_the_last_regular_week(conn) -> None:
    _season_id, _member_id, team_id = _seed_minimal_league(conn, week=LAST_REGULAR_WEEK)
    snapshot = SnapshotRepository(conn).load(horizon_weeks=3)
    assert snapshot.weeks == (LAST_REGULAR_WEEK,)
    team = _seeded_team(snapshot, team_id)
    assert sorted(team.starters()[0].projected_points) == [LAST_REGULAR_WEEK]


def test_a_horizon_shorter_than_a_week_is_refused(conn) -> None:
    with pytest.raises(ValueError, match="horizon_weeks"):
        SnapshotRepository(conn).load(horizon_weeks=0)


def test_a_stalled_roster_sync_behind_fresh_projections_reads_stale(conn) -> None:
    """The whole point of ruling 1: one fresh sync cannot vouch for a stale one."""
    stalled = SEEDED_AT - timedelta(hours=6)
    _season_id, _member_id, _team_id = _seed_minimal_league(conn, holdings_synced_at=stalled)
    snapshot = SnapshotRepository(conn).load()
    assert snapshot.synced_at == SEEDED_AT
    assert snapshot.oldest_synced_at == stalled
    assert snapshot.is_stale(SEEDED_AT + timedelta(minutes=5))
    assert snapshot.age(SEEDED_AT) == timedelta(hours=6)


def test_a_team_without_a_projection_row_is_unavailable(conn) -> None:
    """A component that is missing is unknown, not epoch-old."""
    _season_id, _member_id, team_id = _seed_minimal_league(conn)
    with conn.cursor() as cur:
        cur.execute("delete from public.team_week_projections where team_id = %s", (team_id,))
    with pytest.raises(SnapshotUnavailable, match="team_week_projections"):
        SnapshotRepository(conn).load()


def test_a_team_without_a_season_state_row_is_unavailable(conn) -> None:
    _season_id, _member_id, team_id = _seed_minimal_league(conn)
    with conn.cursor() as cur:
        cur.execute("delete from public.team_season_state where team_id = %s", (team_id,))
    with pytest.raises(SnapshotUnavailable, match="team_season_state"):
        SnapshotRepository(conn).load()


def test_load_runs_a_fixed_number_of_queries(conn) -> None:
    _seed_minimal_league(conn)
    counting = _CountingConnection(conn)
    SnapshotRepository(counting).load(horizon_weeks=3)
    assert counting.executes == LOAD_QUERY_COUNT


def test_the_rendered_label_prefers_nickname_then_sleeper_display_name(conn) -> None:
    _season_id, _member_id, team_id = _seed_minimal_league(conn)
    with conn.cursor() as cur:
        cur.execute("update public.members set sleeper_display_name = 'sleeper01'")
    team = _seeded_team(SnapshotRepository(conn).load(), team_id)
    assert team.member_label == "sleeper01" and team.display_name == "Member01"

    with conn.cursor() as cur:
        cur.execute("update public.members set nickname = 'The Commish'")
    snapshot = SnapshotRepository(conn).load()
    assert _seeded_team(snapshot, team_id).member_label == "The Commish"
    assert snapshot.member_names() == ("The Commish",)
    assert snapshot.team_by_name("the commish").team_id == team_id
    assert snapshot.team_by_name("Member01") is not None


def test_an_eliminated_team_reads_its_frozen_roster(conn) -> None:
    season_id, _member_id, team_id = _seed_minimal_league(conn)
    frozen = SEEDED_AT - timedelta(days=7)
    with conn.cursor() as cur:
        cur.execute(
            "update public.team_season_state set is_eliminated = true, eliminated_week = 4,"
            " elimination_source = 'adjudicator' where team_id = %s",
            (team_id,),
        )
        cur.execute(
            "insert into public.final_rosters"
            " (season_id, team_id, eliminated_week, holdings, frozen_at)"
            " values (%s, %s, 4, %s, %s)",
            (
                season_id,
                team_id,
                Jsonb(
                    [
                        {
                            "sleeper_player_id": "px1",
                            "slot": "starter",
                            "slot_index": 0,
                            "lineup_position": "WR",
                        }
                    ]
                ),
                frozen,
            ),
        )
    snapshot = SnapshotRepository(conn).load()
    team = _seeded_team(snapshot, team_id)
    assert team.is_eliminated and team.elimination_source == "adjudicator"
    # px2 is still a live holding, but it is not the roster this team went out
    # with, so the agent never sees it.
    assert [h.sleeper_player_id for h in team.holdings] == ["px1"]
    # The frozen roster is the oldest component, and it is what age is judged on.
    assert snapshot.oldest_synced_at == frozen


def test_an_eliminated_team_without_a_snapshot_falls_back_to_live_holdings(conn) -> None:
    _season_id, _member_id, team_id = _seed_minimal_league(conn)
    with conn.cursor() as cur:
        cur.execute(
            "update public.team_season_state set is_eliminated = true,"
            " elimination_source = 'manual' where team_id = %s",
            (team_id,),
        )
    team = _seeded_team(SnapshotRepository(conn).load(), team_id)
    assert sorted(h.sleeper_player_id for h in team.holdings) == ["px1", "px2"]


# --- helpers -----------------------------------------------------------------


def _seeded_team(snapshot: LeagueSnapshot, team_id: int):
    """The team the seed actually inserted, never whichever one sorted first."""
    team = next((t for t in snapshot.teams if t.team_id == team_id), None)
    assert team is not None, f"team {team_id} missing from the snapshot"
    return team


class _CountingCursor:
    def __init__(self, cursor, owner: "_CountingConnection") -> None:
        self._cursor = cursor
        self._owner = owner

    def execute(self, *args, **kwargs):
        self._owner.executes += 1
        return self._cursor.execute(*args, **kwargs)

    def __enter__(self):
        self._cursor.__enter__()
        return self

    def __exit__(self, *exc):
        return self._cursor.__exit__(*exc)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _CountingConnection:
    """A pass-through connection that counts every statement run through it."""

    def __init__(self, conn) -> None:
        self._conn = conn
        self.executes = 0

    def cursor(self, *args, **kwargs):
        return _CountingCursor(self._conn.cursor(*args, **kwargs), self)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _seed_nfl_state(conn, week: int = 6) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.nfl_state (id, season, season_type, week, raw, synced_at)"
            " values (1, %(season)s, 'regular', %(week)s, '{}', %(synced)s)"
            " on conflict (id) do update set season = %(season)s, season_type = 'regular',"
            " week = %(week)s, synced_at = %(synced)s",
            {"season": SENTINEL_SEASON, "week": week, "synced": SEEDED_AT},
        )


def _seed_season(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.seasons (year, sleeper_league_id, rules_version, waiver_budget)"
            " values (%s, 'L1', 'v1', 1000) returning id",
            (SENTINEL_SEASON,),
        )
        return cur.fetchone()[0]


def _seed_minimal_league(
    conn,
    *,
    week: int = 6,
    weeks: tuple[int, ...] | None = None,
    holdings_synced_at: datetime | None = None,
) -> tuple[int, int, int]:
    """One sentinel season, one member, one team, one starter and one bench player.

    The season is :data:`SENTINEL_SEASON`, which no sync writes, so nothing here
    depends on -- or collides with -- the real rows in a developer's local stack.
    ``weeks`` is which weeks get projection rows, for the horizon tests.
    """
    weeks = weeks or (week,)
    held_at = SEEDED_AT if holdings_synced_at is None else holdings_synced_at
    _seed_nfl_state(conn, week)
    season_id = _seed_season(conn)
    with conn.cursor() as cur:
        cur.execute("insert into public.members (display_name) values ('Member01') returning id")
        member_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.teams"
            " (season_id, member_id, sleeper_user_id, sleeper_roster_id, team_name)"
            " values (%s, %s, 'u1', 1, 'Team 01') returning id",
            (season_id, member_id),
        )
        team_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.team_season_state"
            " (season_id, team_id, faab_budget, faab_used, synced_at)"
            " values (%s, %s, 1000, 300, %s)",
            (season_id, team_id, SEEDED_AT),
        )
        for pid, name, slot, index in (
            ("px1", "Player X1", "starter", 0),
            ("px2", "Player X2", "bench", None),
        ):
            cur.execute(
                "insert into public.players"
                " (sleeper_player_id, full_name, position, team, synced_at)"
                " values (%s, %s, 'WR', 'KC', %s)",
                (pid, name, SEEDED_AT),
            )
            cur.execute(
                "insert into public.roster_holdings (season_id, team_id, sleeper_player_id,"
                " slot, slot_index, lineup_position, synced_at)"
                " values (%s, %s, %s, %s, %s, %s, %s)",
                (
                    season_id,
                    team_id,
                    pid,
                    slot,
                    index,
                    "WR" if slot == "starter" else None,
                    held_at,
                ),
            )
        for offset, projection_week in enumerate(weeks):
            starter_points = Decimal("18.50") - Decimal("1.50") * offset
            bench_points = Decimal("9.25") - Decimal("1.00") * offset
            cur.execute(
                "insert into public.team_week_projections (season_id, team_id, week,"
                " projected_points, starter_slots, filled_slots, empty_slots,"
                " starters_projected, missing_projections, coverage_pct, computed_at)"
                " values (%s, %s, %s, %s, 1, 1, 0, 1, 0, 100.0, %s)",
                (season_id, team_id, projection_week, starter_points, SEEDED_AT),
            )
            for pid, points in (("px1", starter_points), ("px2", bench_points)):
                cur.execute(
                    "insert into public.player_projections (season, week, sleeper_player_id,"
                    " stat_line, league_points, scoring_version, projected_at, synced_at)"
                    " values (%s, %s, %s, '{}', %s, 'v1', %s, %s)",
                    (SENTINEL_SEASON, projection_week, pid, points, SEEDED_AT, SEEDED_AT),
                )
    return season_id, member_id, team_id
