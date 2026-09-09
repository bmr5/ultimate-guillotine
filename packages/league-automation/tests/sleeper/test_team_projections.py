from datetime import UTC, datetime
from decimal import Decimal

from ultimate_guillotine.sleeper.team_projections import (
    StarterTally,
    build_team_week,
    coverage_pct,
    recompute_team_week,
    run_coverage,
)

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def test_coverage_is_projected_over_filled_and_100_when_nothing_is_filled() -> None:
    assert coverage_pct(9, 9) == Decimal("100.00")
    assert coverage_pct(8, 9) == Decimal("88.89")
    assert coverage_pct(0, 0) == Decimal("100.00")


def test_run_coverage_ignores_eliminated_teams() -> None:
    tallies = [
        StarterTally(1, 9, 9, Decimal("110.00"), is_eliminated=False),
        StarterTally(2, 9, 8, Decimal("100.00"), is_eliminated=False),
        StarterTally(3, 9, 0, Decimal("0.00"), is_eliminated=True),
    ]
    assert run_coverage(tallies) == Decimal("94.44")
    healthy = [t for t in tallies if not t.is_eliminated]
    assert run_coverage(healthy + [StarterTally(4, 9, 9, Decimal(90), False)]) == (
        Decimal("96.30")
    )


def test_empty_slots_contribute_zero_and_leave_coverage_alone() -> None:
    # 7 of 9 slots filled, all 7 projected: coverage is 100, empty_slots is 2.
    rows = build_team_week(
        [StarterTally(1, 7, 7, Decimal("98.40"), False)], starter_slots=9,
        run_pct=Decimal("100.00"),
    )
    row = rows[0]
    assert row.empty_slots == 2 and row.filled_slots == 7
    assert row.coverage_pct == Decimal("100.00") and row.missing_projections == 0
    assert row.projected_points == Decimal("98.40") and not row.is_provisional


def test_a_missing_projection_lowers_coverage_and_flags_provisional() -> None:
    rows = build_team_week(
        [StarterTally(1, 9, 8, Decimal("101.00"), False)], starter_slots=9,
        run_pct=Decimal("99.00"),
    )
    row = rows[0]
    assert row.missing_projections == 1
    assert row.coverage_pct == Decimal("88.89") and row.is_provisional


def test_a_failing_run_gate_makes_every_team_provisional() -> None:
    rows = build_team_week(
        [StarterTally(1, 9, 9, Decimal("120.00"), False)], starter_slots=9,
        run_pct=Decimal("81.25"),
    )
    assert rows[0].coverage_pct == Decimal("100.00") and rows[0].is_provisional


def test_recompute_sums_starter_projections_for_the_week(conn) -> None:
    season_id, team_id = _seed(conn)
    rows, run_pct = recompute_team_week(conn, season_id, 2026, 1, NOW)
    row = next(r for r in rows if r.team_id == team_id)
    # 20.00 (starter with a projection) + 0 for the starter without one.
    assert row.projected_points == Decimal("20.00")
    assert (row.filled_slots, row.starters_projected, row.missing_projections) == (2, 1, 1)
    assert row.empty_slots == 7 and row.coverage_pct == Decimal("50.00")
    assert row.is_provisional and run_pct == Decimal("50.00")
    with conn.cursor() as cur:
        cur.execute(
            "select projected_points, coverage_pct, is_provisional, computed_at "
            "from public.team_week_projections where team_id = %s and week = 1",
            (team_id,),
        )
        assert cur.fetchone() == (Decimal("20.00"), Decimal("50.00"), True, NOW)


def test_recompute_is_idempotent(conn) -> None:
    season_id, team_id = _seed(conn)
    recompute_team_week(conn, season_id, 2026, 1, NOW)
    recompute_team_week(conn, season_id, 2026, 1, NOW)
    with conn.cursor() as cur:
        cur.execute(
            "select count(*) from public.team_week_projections where team_id = %s",
            (team_id,),
        )
        assert cur.fetchone()[0] == 1


def _seed(conn) -> tuple[int, int]:
    """One season with nine starter slots, one team, two starters, one projection."""
    with conn.cursor() as cur:
        cur.execute(
            "update public.seasons set roster_positions = "
            "'[\"QB\",\"RB\",\"RB\",\"WR\",\"WR\",\"TE\",\"FLEX\",\"K\",\"DEF\"]' "
            "where year = 2026 returning id"
        )
        season_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.members (display_name) values ('Coverage Member') "
            "returning id"
        )
        member_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.teams (season_id, member_id, sleeper_user_id, "
            "sleeper_roster_id, team_name) values (%s, %s, 'u', 901, 'T') returning id",
            (season_id, member_id),
        )
        team_id = cur.fetchone()[0]
        cur.executemany(
            "insert into public.roster_holdings (season_id, team_id, sleeper_player_id, "
            "slot, slot_index, lineup_position, synced_at) values (%s, %s, %s, %s, %s, "
            "%s, now())",
            [
                (season_id, team_id, "p1", "starter", 0, "QB"),
                (season_id, team_id, "p2", "starter", 1, "RB"),
                (season_id, team_id, "p3", "bench", None, None),
            ],
        )
        cur.executemany(
            "insert into public.player_projections (season, week, sleeper_player_id, "
            "stat_line, league_points, scoring_version, projected_at, synced_at) "
            "values (2026, 1, %s, '{}'::jsonb, %s, 'v1', now(), now())",
            [("p1", Decimal("20.00")), ("p3", Decimal("30.00"))],
        )
    return season_id, team_id


def test_a_null_league_points_row_is_missing_not_zero(conn) -> None:
    """A player who left the feed keeps his row with null points -- still uncovered."""
    season_id, team_id = _seed(conn)
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.player_projections (season, week, sleeper_player_id, "
            "stat_line, league_points, scoring_version, projected_at, synced_at) "
            "values (2026, 1, 'p2', '{}'::jsonb, null, 'v1', now(), now())"
        )
    rows, run_pct = recompute_team_week(conn, season_id, 2026, 1, NOW)
    row = next(r for r in rows if r.team_id == team_id)
    assert (row.filled_slots, row.starters_projected, row.missing_projections) == (2, 1, 1)
    assert row.projected_points == Decimal("20.00")
    assert row.coverage_pct == Decimal("50.00") and run_pct == Decimal("50.00")


def test_an_eliminated_team_is_off_the_run_gate_but_still_gets_a_row(conn) -> None:
    season_id, team_id = _seed(conn)
    dead_id = _eliminated_team(conn, season_id)
    rows, run_pct = recompute_team_week(conn, season_id, 2026, 1, NOW)
    # The dead team's unprojected starter is not counted against the run.
    assert run_pct == Decimal("50.00")
    dead = next(r for r in rows if r.team_id == dead_id)
    assert dead.filled_slots == 1 and dead.starters_projected == 0
    assert dead.coverage_pct == Decimal("0.00") and dead.is_provisional
    live = next(r for r in rows if r.team_id == team_id)
    assert live.coverage_pct == Decimal("50.00")


def _eliminated_team(conn, season_id: int) -> int:
    """A second team, out of the league, holding one starter nobody projected."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.members (display_name) values ('Dead Member') returning id"
        )
        member_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.teams (season_id, member_id, sleeper_user_id, "
            "sleeper_roster_id, team_name) values (%s, %s, 'u2', 902, 'D') returning id",
            (season_id, member_id),
        )
        team_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.roster_holdings (season_id, team_id, sleeper_player_id, "
            "slot, slot_index, lineup_position, synced_at) "
            "values (%s, %s, 'p9', 'starter', 0, 'QB', now())",
            (season_id, team_id),
        )
        cur.execute(
            "insert into public.team_season_state (season_id, team_id, faab_budget, "
            "faab_used, is_eliminated, synced_at) values (%s, %s, 100, 0, true, now())",
            (season_id, team_id),
        )
    return team_id
