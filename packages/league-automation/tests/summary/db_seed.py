"""One sentinel league in the local database, for the EOD repository tests.

Modelled on the Advisor's seed in ``tests/advisor/test_state.py``: a season year no
sync will ever write, so nothing here depends on -- or collides with -- the real
rows a developer's local stack carries, and the ``conn`` fixture rolls every row
back on the way out.

Three teams, so a gulag pairing, a pool and an eliminated team can all exist at
once: team 1 and team 2 are the week 3 gulag by the Adjudicator's events, team 3
went out in week 2. Two starter slots each.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from psycopg.types.json import Jsonb

SENTINEL_SEASON = 2098
WEEK = 3
SEEDED_AT = datetime(2098, 9, 27, 4, 30, tzinfo=UTC)
#: ``now`` for a run over this seed: a Saturday night in Central time, so "today"
#: since local midnight is the window one of the two transactions falls in.
NOW = SEEDED_AT

#: (player id, name, position, NFL team, injury status), two starters per team.
PLAYERS = {
    1: (("p1a", "One A", "QB", "PHI", None), ("p1b", "One B", "RB", "KC", None)),
    2: (("p2a", "Two A", "QB", "DAL", "Out"), ("p2b", "Two B", "RB", "DEN", "Questionable")),
    3: (("p3a", "Three A", "QB", "SF", None), ("p3b", "Three B", "RB", "SEA", None)),
}
#: Only the dropped player, never rostered, so the moves line has to look him up.
DROPPED = ("p9z", "Nine Z", "WR", "NYJ", None)


def seed_league(conn) -> tuple[int, dict[int, int]]:
    """Insert the league and return ``(season_id, {roster_id: team_id})``."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.nfl_state (id, season, season_type, week, raw, synced_at)"
            " values (1, %(season)s, 'regular', %(week)s, '{}', %(synced)s)"
            " on conflict (id) do update set season = %(season)s, season_type = 'regular',"
            " week = %(week)s, synced_at = %(synced)s",
            {"season": SENTINEL_SEASON, "week": WEEK, "synced": SEEDED_AT},
        )
        cur.execute(
            "insert into public.seasons (year, sleeper_league_id, rules_version, waiver_budget,"
            " roster_positions) values (%s, 'L1', 'v1', 1000, %s) returning id",
            (SENTINEL_SEASON, Jsonb(["QB", "RB"])),
        )
        season_id = cur.fetchone()[0]
        for pid, name, position, nfl_team, injury in (*sum(PLAYERS.values(), ()), DROPPED):
            cur.execute(
                "insert into public.players (sleeper_player_id, full_name, position, team,"
                " injury_status, synced_at) values (%s, %s, %s, %s, %s, %s)",
                (pid, name, position, nfl_team, injury, SEEDED_AT),
            )
        teams: dict[int, int] = {}
        for roster_id in (1, 2, 3):
            cur.execute(
                "insert into public.members (display_name, nickname) values (%s, %s)"
                " returning id",
                (f"eod-seed-{roster_id}", f"Nick{roster_id}"),
            )
            member_id = cur.fetchone()[0]
            cur.execute(
                "insert into public.teams (season_id, member_id, sleeper_user_id,"
                " sleeper_roster_id, team_name) values (%s, %s, %s, %s, %s) returning id",
                (season_id, member_id, f"u{roster_id}", roster_id, f"Team {roster_id}"),
            )
            team_id = cur.fetchone()[0]
            teams[roster_id] = team_id
            eliminated = roster_id == 3
            cur.execute(
                "insert into public.team_season_state (season_id, team_id, faab_budget,"
                " faab_used, is_eliminated, eliminated_week, elimination_source, synced_at)"
                " values (%s, %s, 1000, %s, %s, %s, %s, %s)",
                (season_id, team_id, 100 * roster_id, eliminated, 2 if eliminated else None,
                 "adjudicator" if eliminated else None, SEEDED_AT),
            )
            for index, (pid, _name, position, _team, _injury) in enumerate(PLAYERS[roster_id]):
                cur.execute(
                    "insert into public.roster_holdings (season_id, team_id, sleeper_player_id,"
                    " slot, slot_index, lineup_position, synced_at)"
                    " values (%s, %s, %s, 'starter', %s, %s, %s)",
                    (season_id, team_id, pid, index, position, SEEDED_AT),
                )
                cur.execute(
                    "insert into public.player_projections (season, week, sleeper_player_id,"
                    " stat_line, league_points, scoring_version, projected_at, synced_at)"
                    " values (%s, %s, %s, '{}', %s, 'v1', %s, %s)",
                    (SENTINEL_SEASON, WEEK, pid, Decimal(10 + roster_id), SEEDED_AT,
                     SEEDED_AT),
                )
            cur.execute(
                "insert into public.team_week_projections (season_id, team_id, week,"
                " projected_points, starter_slots, filled_slots, empty_slots,"
                " starters_projected, missing_projections, coverage_pct, computed_at)"
                " values (%s, %s, %s, %s, 2, 2, 0, 2, 0, 100.0, %s)",
                (season_id, team_id, WEEK, Decimal(20 + 2 * roster_id), SEEDED_AT),
            )
            if eliminated:
                cur.execute(
                    "insert into public.final_rosters (season_id, team_id, eliminated_week,"
                    " holdings, frozen_at) values (%s, %s, 2, %s, %s)",
                    (season_id, team_id, Jsonb([
                        {"sleeper_player_id": pid, "slot": "starter", "slot_index": index,
                         "lineup_position": position}
                        for index, (pid, _n, position, _t, _i) in enumerate(PLAYERS[3])
                    ]), SEEDED_AT),
                )
            # Three weeks of scores: two past weeks for the replay, this week live.
            for week in (1, 2, WEEK):
                cur.execute(
                    "insert into public.team_week_scores (season_id, team_id, week, points,"
                    " players_points, starters, synced_at) values (%s, %s, %s, %s, %s, %s, %s)",
                    (season_id, team_id, week, Decimal(50 + 10 * roster_id + week),
                     Jsonb({PLAYERS[roster_id][0][0]: 12.5}),
                     [p[0] for p in PLAYERS[roster_id]], SEEDED_AT),
                )
        for team_id in (teams[1], teams[2]):
            cur.execute(
                "insert into public.league_events (season_id, week, event_type, occurred_at,"
                " payload) values (%s, %s, 'gulag_entry', %s, %s)",
                (season_id, WEEK, SEEDED_AT, Jsonb({"team_id": team_id})),
            )
        # One waiver claim tonight and one two days ago, so "since local midnight" bites.
        for offset_hours, tx_id in ((1, "tx-today"), (50, "tx-old")):
            occurred = SEEDED_AT - timedelta(hours=offset_hours)
            cur.execute(
                "insert into public.transactions (season_id, sleeper_transaction_id, kind,"
                " week, occurred_at, team_ids, faab_moves, waiver_bid, raw, synced_at)"
                " values (%s, %s, 'waiver', %s, %s, %s, '[]', 12, '{}', %s) returning id",
                (season_id, tx_id, WEEK, occurred, [teams[1]], SEEDED_AT),
            )
            transaction_id = cur.fetchone()[0]
            for pid, action in (("p1b", "add"), ("p9z", "drop")):
                cur.execute(
                    "insert into public.transaction_moves (transaction_id, season_id,"
                    " sleeper_player_id, team_id, action) values (%s, %s, %s, %s, %s)",
                    (transaction_id, season_id, pid, teams[1], action),
                )
    return season_id, teams
