from datetime import UTC, datetime, timedelta

import pytest
from psycopg.types.json import Jsonb

from tests.advisor.fixture import (
    ASKER_MEMBER_ID,
    ELIMINATED_MEMBER_ID,
    FIXTURE_SYNCED_AT,
    fixture_snapshot,
)
from ultimate_guillotine.advisor.state import (
    COVERAGE_GATE,
    SnapshotRepository,
    SnapshotUnavailable,
)


def test_fixture_has_eighteen_teams_with_a_known_pressure_order() -> None:
    snapshot = fixture_snapshot()
    assert len(snapshot.teams) == 18
    totals = [team.projected_points for team in snapshot.teams]
    assert totals == sorted(totals, reverse=True)
    assert snapshot.teams[ELIMINATED_MEMBER_ID - 1].is_eliminated
    assert snapshot.coverage_ok()


def test_starters_and_bench_split_on_the_slot_column() -> None:
    team = fixture_snapshot().team_for_member(ASKER_MEMBER_ID)
    assert len(team.starters()) == 8 and len(team.bench()) == 6
    assert all(h.slot == "starter" for h in team.starters())
    assert all(h.slot == "bench" for h in team.bench())


def test_below_the_gate_every_projection_is_withheld() -> None:
    snapshot = fixture_snapshot(coverage_pct=90.0)
    assert not snapshot.coverage_ok()
    assert all(team.is_provisional for team in snapshot.teams)
    assert all(team.projected_points is None for team in snapshot.teams)
    # The counting fallback only gets exercised if the holdings go dark too.
    assert all(
        h.projected_points is None for team in snapshot.teams for h in team.holdings
    )
    assert COVERAGE_GATE == 95.0


def test_staleness_is_measured_from_synced_at() -> None:
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


def test_load_reads_one_week_of_the_data_layer(conn) -> None:
    _seed_minimal_league(conn)
    snapshot = SnapshotRepository(conn).load()
    assert snapshot.season == 2026 and snapshot.week == 6
    assert len(snapshot.teams) == 1
    team = snapshot.teams[0]
    assert team.display_name == "Member01" and team.faab_remaining == 700
    assert [h.sleeper_player_id for h in team.starters()] == ["px1"]
    assert team.starters()[0].projected_points == pytest.approx(18.5)
    assert team.starters()[0].player_name == "Player X1"
    assert team.bench()[0].sleeper_player_id == "px2"
    assert snapshot.synced_at == datetime(2026, 10, 8, 15, 0, tzinfo=UTC)


def test_the_rendered_label_prefers_nickname_then_sleeper_display_name(conn) -> None:
    _seed_minimal_league(conn)
    with conn.cursor() as cur:
        cur.execute("update public.members set sleeper_display_name = 'sleeper01'")
    team = SnapshotRepository(conn).load().teams[0]
    assert team.member_label == "sleeper01" and team.display_name == "Member01"

    with conn.cursor() as cur:
        cur.execute("update public.members set nickname = 'The Commish'")
    snapshot = SnapshotRepository(conn).load()
    assert snapshot.teams[0].member_label == "The Commish"
    assert snapshot.member_names() == ("The Commish",)
    assert snapshot.team_by_name("the commish").member_id == snapshot.teams[0].member_id
    assert snapshot.team_by_name("Member01") is not None


def test_an_eliminated_team_reads_its_frozen_roster(conn) -> None:
    season_id, _member_id, team_id = _seed_minimal_league(conn)
    frozen = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
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
    team = SnapshotRepository(conn).load().teams[0]
    assert team.is_eliminated and team.elimination_source == "adjudicator"
    # px2 is still a live holding, but it is not the roster this team went out
    # with, so the Advisor never sees it.
    assert [h.sleeper_player_id for h in team.holdings] == ["px1"]


def test_an_eliminated_team_without_a_snapshot_falls_back_to_live_holdings(conn) -> None:
    _season_id, _member_id, team_id = _seed_minimal_league(conn)
    with conn.cursor() as cur:
        cur.execute(
            "update public.team_season_state set is_eliminated = true,"
            " elimination_source = 'manual' where team_id = %s",
            (team_id,),
        )
    team = SnapshotRepository(conn).load().teams[0]
    assert sorted(h.sleeper_player_id for h in team.holdings) == ["px1", "px2"]


def _seed_minimal_league(conn) -> tuple[int, int, int]:
    """One season, one member, one team, one starter and one bench player."""
    synced = datetime(2026, 10, 8, 15, 0, tzinfo=UTC)
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.nfl_state (id, season, season_type, week, raw, synced_at)"
            " values (1, 2026, 'regular', 6, '{}', %s)"
            " on conflict (id) do update set season = 2026, season_type = 'regular',"
            " week = 6, synced_at = %s",
            (synced, synced),
        )
        # The local database already carries the real 2026 season row, so this
        # upserts rather than inserting: the year is unique.
        cur.execute(
            "insert into public.seasons (year, sleeper_league_id, rules_version, waiver_budget)"
            " values (2026, 'L1', 'v1', 1000)"
            " on conflict (year) do update set waiver_budget = excluded.waiver_budget"
            " returning id"
        )
        season_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.members (display_name) values ('Member01') returning id"
        )
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
            (season_id, team_id, synced),
        )
        cur.execute(
            "insert into public.team_week_projections (season_id, team_id, week,"
            " projected_points, starter_slots, filled_slots, empty_slots,"
            " starters_projected, missing_projections, coverage_pct, computed_at)"
            " values (%s, %s, 6, 18.5, 1, 1, 0, 1, 0, 100.0, %s)",
            (season_id, team_id, synced),
        )
        for pid, name, slot, index, points in (
            ("px1", "Player X1", "starter", 0, 18.5),
            ("px2", "Player X2", "bench", None, 9.25),
        ):
            cur.execute(
                "insert into public.players"
                " (sleeper_player_id, full_name, position, team, synced_at)"
                " values (%s, %s, 'WR', 'KC', %s)",
                (pid, name, synced),
            )
            cur.execute(
                "insert into public.roster_holdings (season_id, team_id, sleeper_player_id,"
                " slot, slot_index, lineup_position, synced_at)"
                " values (%s, %s, %s, %s, %s, %s, %s)",
                (season_id, team_id, pid, slot, index, "WR" if slot == "starter" else None,
                 synced),
            )
            cur.execute(
                "insert into public.player_projections (season, week, sleeper_player_id,"
                " stat_line, league_points, scoring_version, projected_at, synced_at)"
                " values (2026, 6, %s, '{}', %s, 'v1', %s, %s)",
                (pid, points, synced, synced),
            )
    return season_id, member_id, team_id
