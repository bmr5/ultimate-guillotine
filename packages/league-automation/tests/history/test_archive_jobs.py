from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from ultimate_guillotine.history.archive_jobs import capture_current, enable, tick
from ultimate_guillotine.history.archive_store import rows
from ultimate_guillotine.sleeper.models import SleeperLeague, SleeperRoster, SleeperUser
from ultimate_guillotine.sleeper.sync import sync_season

START = datetime(2026, 9, 10, 15, tzinfo=UTC)
MONDAY = datetime(2026, 9, 15, 4, 30, tzinfo=UTC)  # Monday 11:30 Central
TUESDAY = datetime(2026, 9, 15, 13, tzinfo=UTC)


class League:
    week = 1
    missing_schedule = False
    missing_score = False

    def __init__(self, league_id):
        self.league_id = league_id
        self.complete, self.amounts, self.roster_players, self.points = set(), {}, {}, {}

    def get_league(self, _):
        return SleeperLeague(
            league_id=self.league_id,
            name="test",
            season="2026",
            total_rosters=18,
            settings={"waiver_budget": 1000},
            roster_positions=["QB"],
        )

    def get_users(self, _):
        return [
            SleeperUser(user_id=f"archive-user-{t}", display_name=f"Archive Manager {t}")
            for t in range(1, 19)
        ]

    def get_rosters(self, _):
        return [
            SleeperRoster(
                roster_id=t,
                owner_id=f"archive-user-{t}",
                players=self.roster_players.get(t, [f"P{t}"]),
                starters=self.roster_players.get(t, [f"P{t}"]),
                settings={"waiver_budget_used": self.amounts.get(t, 100)},
            )
            for t in range(1, 19)
        ]

    def get_matchups(self, _, week):
        return [
            {
                "roster_id": t,
                "points": None if self.missing_score and t == 1 else self.points.get((week, t), t),
                "custom_points": None,
                "players": [f"P{t}"],
                "starters": [f"P{t}"],
                "players_points": {f"P{t}": self.points.get((week, t), t)},
            }
            for t in range(1, 19)
        ]

    def get_nfl_state(self):
        return {"season": "2026", "season_type": "regular", "week": self.week}

    def get_schedule(self, _):
        if self.missing_schedule:
            return []
        return [
            {
                "game_id": f"w{w}g{g}",
                "week": w,
                "date": (
                    date(2026, 9, 10) + timedelta(weeks=w - 1, days=4 if g == 15 else 0)
                ).isoformat(),
                "home": f"H{g}",
                "away": f"A{g}",
                "status": "complete" if w in self.complete else "pre_game",
            }
            for w in range(1, 19)
            for g in range(16)
        ]


@pytest.fixture
def archive(conn):
    root = Path(__file__).resolve().parents[4]
    for name in (
        "20260911010000_season_event_archive.sql",
        "20260911011000_archive_automation.sql",
    ):
        conn.execute((root / "supabase" / "migrations" / name).read_text())
    season_id, league_id = conn.execute(
        "select id,sleeper_league_id from public.seasons where year=2026"
    ).fetchone()
    client = League(league_id)
    sync_season(client, conn, 2026, league_id, week=1)
    enable(conn, client, league_id, 2026, "production", START)
    return conn, client, season_id


def current(conn, week=1):
    return rows(conn, "select * from public.season_history_current_weeks where week=%s", (week,))[0]


def finalize_week_one(conn, client):
    capture_current(conn, client, MONDAY - timedelta(minutes=5))
    client.complete.add(1)
    assert tick(conn, client, MONDAY)["pending"] == 1
    assert tick(conn, client, TUESDAY)["confirmed"] == 1


def test_week_one_automatic_idempotent_and_balances_frozen(archive):
    conn, client, _ = archive
    capture_current(conn, client, MONDAY - timedelta(minutes=5))
    client.complete.add(1)
    tick(conn, client, MONDAY)
    assert current(conn)["status"] == "provisional"
    # Roster clearing and new balances before morning verification do not rewrite Monday.
    client.roster_players[1], client.amounts[1] = [], 700
    tick(conn, client, TUESDAY)
    row = current(conn)
    assert row["status"] == "confirmed" and row["remaining_teams"] == 18
    snapshots = rows(
        conn,
        "select * from public.team_event_snapshots where week_revision_id=%s order by team_id",
        (row["id"],),
    )
    assert len(snapshots) == 2
    assert {e["event_type"] for e in snapshots} == {"gulag_qualified"}
    assert snapshots[0]["faab_remaining"] == 900
    assert rows(
        conn,
        "select player_id from public.team_event_players where snapshot_id=%s",
        (snapshots[0]["id"],),
    ) == [{"player_id": "P1"}]
    assert (
        conn.execute(
            "select count(*) from public.team_season_state where is_eliminated"
        ).fetchone()[0]
        == 0
    )
    tick(conn, client, TUESDAY + timedelta(hours=1))
    assert current(conn)["id"] == row["id"]


def test_missing_game_and_missing_scores_cannot_finalize(archive):
    conn, client, _ = archive
    tick(conn, client, TUESDAY)
    assert not rows(conn, "select * from public.season_history_current_weeks")
    client.complete.add(1)
    client.missing_score = True
    tick(conn, client, TUESDAY + timedelta(minutes=15))
    assert current(conn)["status"] == "unresolved"
    assert (
        conn.execute(
            "select count(*) from public.team_season_state where is_eliminated"
        ).fetchone()[0]
        == 0
    )


def test_late_start_needs_two_stable_reads_and_reports_partial_coverage(archive):
    conn, client, _ = archive
    client.complete.add(1)
    tick(conn, client, TUESDAY)
    assert current(conn)["status"] == "provisional"
    tick(conn, client, TUESDAY + timedelta(minutes=15))
    assert current(conn)["status"] == "provisional"
    tick(conn, client, TUESDAY + timedelta(minutes=30))
    assert current(conn)["status"] == "confirmed"
    assert rows(
        conn, "select distinct roster_coverage from public.season_history_current_events"
    ) == [{"roster_coverage": "partial"}]


def test_week_two_gulag_and_score_correction_updates_cut_without_new_roster(archive):
    conn, client, _ = archive
    finalize_week_one(conn, client)
    client.week = 2
    before = MONDAY + timedelta(weeks=1) - timedelta(minutes=5)
    capture_current(conn, client, before)
    client.complete.add(2)
    tick(conn, client, MONDAY + timedelta(weeks=1))
    tick(conn, client, TUESDAY + timedelta(weeks=1))
    assert current(conn, 2)["remaining_teams"] == 17
    cuts = rows(
        conn,
        "select team_id from public.team_event_snapshots where week_revision_id=%s and event_type='eliminated'",
        (current(conn, 2)["id"],),
    )
    first = cuts[0]["team_id"]
    client.points[(2, 1)] = 100
    client.roster_players[2] = []
    correction_time = TUESDAY + timedelta(weeks=1, hours=2)
    tick(conn, client, correction_time)
    tick(conn, client, correction_time + timedelta(minutes=30))
    cuts = rows(
        conn,
        "select id,team_id from public.team_event_snapshots where week_revision_id=%s and event_type='eliminated'",
        (current(conn, 2)["id"],),
    )
    assert cuts[0]["team_id"] != first
    assert rows(
        conn,
        "select player_id from public.team_event_players where snapshot_id=%s",
        (cuts[0]["id"],),
    ) == [{"player_id": "P2"}]
    assert (
        conn.execute(
            "select count(*) from public.team_season_state where is_eliminated"
        ).fetchone()[0]
        == 1
    )


def test_capture_pins_unfinished_week_across_sleeper_rollover(archive):
    conn, client, _ = archive
    client.week = 2
    assert capture_current(conn, client, TUESDAY) == 2
    assert {
        r["week"] for r in rows(conn, "select distinct week from private.team_state_observations")
    } == {1, 2}


def test_schedule_failure_keeps_available_roster_evidence(archive):
    conn, client, _ = archive
    client.missing_schedule = True
    capture_current(conn, client, MONDAY)
    assert conn.execute("select count(*) from private.team_state_observations").fetchone()[0] == 1
    tick(conn, client, TUESDAY)
    assert current(conn)["status"] == "unresolved"


def test_worker_can_capture_and_confirm_and_public_cannot_read_evidence(archive):
    conn, client, _ = archive
    try:
        conn.execute("set local role automation_worker")
    except psycopg.errors.InsufficientPrivilege:
        pytest.skip("test database user cannot assume the worker role")
    finalize_week_one(conn, client)
    assert current(conn)["status"] == "confirmed"
    assert current(conn)["is_correction"] is False
    conn.execute("reset role")
    assert not conn.execute(
        "select has_table_privilege('anon','private.team_state_observations','SELECT')"
    ).fetchone()[0]


def test_substitute_takes_the_loss_and_correction_withdraws_dependent_week(archive):
    from ultimate_guillotine.cli.archive import Ruling, record_ruling
    from ultimate_guillotine.history.archive_jobs import configuration
    from ultimate_guillotine.history.archive_store import current_gulag_events

    conn, client, _ = archive
    finalize_week_one(conn, client)
    ids = dict(conn.execute("select sleeper_roster_id,id from public.teams").fetchall())
    record_ruling(
        conn,
        configuration(conn),
        Ruling(
            week=2,
            actor="Commish",
            reason="Team 3 takes Team 1's gulag place",
            substitutions={ids[1]: ids[3]},
        ),
        TUESDAY,
    )
    pair = current_gulag_events(conn, configuration(conn)["season_id"])[0][2]["team_ids"]
    assert set(pair) == {ids[2], ids[3]}
    client.week = 2
    client.points[(2, 3)] = 0
    client.complete.add(2)
    tick(conn, client, MONDAY + timedelta(weeks=1))
    tick(conn, client, TUESDAY + timedelta(weeks=1))
    event = rows(
        conn,
        "select * from public.team_event_snapshots where week_revision_id=%s and event_type='eliminated'",
        (current(conn, 2)["id"],),
    )[0]
    assert event["team_id"] == ids[3]
    assert event["qualifier_team_id"] == ids[1]
    assert event["beneficiary_team_id"] == ids[1]
    assert (
        conn.execute(
            "select is_eliminated from public.team_season_state where team_id=%s", (ids[1],)
        ).fetchone()[0]
        is False
    )
    assert rows(conn, "select team_id from public.effective_final_rosters") == [{"team_id": ids[3]}]
    # An earlier correction changes qualifiers. The old substitution no longer applies.
    client.points[(1, 1)] = 100
    later = TUESDAY + timedelta(weeks=1, days=1, hours=2)
    tick(conn, client, later)
    tick(conn, client, later + timedelta(minutes=30))
    assert current(conn)["is_correction"] is True
    assert current(conn, 2)["status"] == "retracted"
    assert not rows(conn, "select * from public.effective_final_rosters")
    assert (
        conn.execute(
            "select count(*) from public.team_season_state where is_eliminated"
        ).fetchone()[0]
        == 0
    )
    assert current_gulag_events(conn, configuration(conn)["season_id"])[0][2]["team_ids"] == []


def test_test_scope_never_changes_official_state(archive):
    conn, client, season_id = archive
    conn.execute("update private.archive_seasons set scope='test' where season_id=%s", (season_id,))
    conn.execute(
        "update private.archive_week_jobs set scope='test' where season_id=%s", (season_id,)
    )
    for week in (1, 2):
        client.week = week
        client.complete.add(week)
        tick(conn, client, MONDAY + timedelta(weeks=week - 1))
        tick(conn, client, TUESDAY + timedelta(weeks=week - 1))
    assert not rows(conn, "select * from public.season_history_current_weeks")
    assert not rows(conn, "select * from public.weekly_results")
    assert (
        conn.execute(
            "select count(*) from public.team_season_state where is_eliminated"
        ).fetchone()[0]
        == 0
    )
    assert rows(
        conn,
        "select status from public.season_history_weeks where week=2 order by revision desc limit 1",
    ) == [{"status": "confirmed"}]
