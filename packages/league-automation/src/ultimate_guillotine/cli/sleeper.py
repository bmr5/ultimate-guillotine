"""`ug sleeper` subcommands."""

import argparse
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import psycopg

from ultimate_guillotine.cli.deps import build_deps, run_scheduled, run_scheduled_with_notes
from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.players import sync_players
from ultimate_guillotine.sleeper.projections import ProjectionRepository, fetch_projection_rows
from ultimate_guillotine.sleeper.scoring import DRIFT_POINTS, scoring_version
from ultimate_guillotine.sleeper.state import current_week, sync_nfl_state
from ultimate_guillotine.sleeper.sync import sync_season
from ultimate_guillotine.sleeper.team_projections import COVERAGE_GATE, recompute_team_week

#: The league's season. The NFL season a projection belongs to is read from
#: `nfl_state`, never from this: the two part company every January.
SYNC_YEAR = 2026


def register(subparsers) -> None:
    parser = subparsers.add_parser("sleeper", help="Sleeper integration commands")
    sleeper_sub = parser.add_subparsers(dest="command", required=True)

    sync_parser = sleeper_sub.add_parser("sync", help="sync members and teams from Sleeper")
    sync_parser.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing on success so a scheduled run delivers only failures",
    )
    sync_parser.set_defaults(handler=cmd_sync)

    players_parser = sleeper_sub.add_parser("players", help="sync the player directory")
    players_parser.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing on success so a scheduled run delivers only failures",
    )
    players_parser.set_defaults(handler=cmd_players)

    state_parser = sleeper_sub.add_parser("state", help="refresh the NFL week row")
    state_parser.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing on success so a scheduled run delivers only failures",
    )
    state_parser.set_defaults(handler=cmd_state)

    proj_parser = sleeper_sub.add_parser("projections", help="sync weekly projections")
    proj_parser.add_argument("--week", type=int, default=None, help="week to sync")
    proj_parser.add_argument(
        "--rescore",
        action="store_true",
        help="recompute points from stored stat lines without refetching",
    )
    proj_parser.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing on success so a scheduled run delivers only failures",
    )
    proj_parser.set_defaults(handler=cmd_projections)


def cmd_sync(args: argparse.Namespace) -> int:
    deps = build_deps()
    conn = deps.conn
    now = datetime.now(UTC)

    def action(run_id: int) -> int:
        client = SleeperClient(httpx.Client())
        state = current_week(client, conn, now)
        # `week` is scoped by `season_type`: preseason week 2 is not regular-season
        # week 2. Outside the regular season there is no week to stamp an inferred
        # elimination with, and None leaves `eliminated_week` null rather than
        # dating an elimination to a preseason or playoff week number.
        week = state.week if state.season_type == "regular" else None
        report = sync_season(client, conn, SYNC_YEAR, deps.settings.sleeper_league_id, week=week)
        if not args.quiet:
            print(
                f"sleeper sync: {report.members} members, {report.teams} teams, "
                f"{report.holdings} holdings, {report.states} team states, "
                f"{report.frozen} rosters frozen"
            )
        return 0

    return run_scheduled_with_notes(deps, "sleeper-sync", now, action)


def cmd_players(args: argparse.Namespace) -> int:
    deps = build_deps()
    conn = deps.conn
    now = datetime.now(UTC)

    def action(run_id: int) -> int:
        written = sync_players(SleeperClient(httpx.Client()), conn, now)
        if not args.quiet:
            print(f"players sync: {written} players")
        return 0

    return run_scheduled(conn, "players-sync", now, action)


def cmd_state(args: argparse.Namespace) -> int:
    deps = build_deps()
    conn = deps.conn
    now = datetime.now(UTC)

    def action(run_id: int) -> int:
        state = sync_nfl_state(SleeperClient(httpx.Client()), conn, now)
        if not args.quiet:
            print(f"nfl state: {state.season} {state.season_type} week {state.week}")
        return 0

    return run_scheduled_with_notes(deps, "nfl-state", now, action)


def _season_row(conn: psycopg.Connection, year: int) -> tuple[int, dict]:
    """The season row's id and scoring settings for the NFL year being projected.

    Looked up by the year `nfl_state` reports rather than by `SYNC_YEAR`, so a
    January run cannot score one season's stat lines with another's settings.
    """
    with conn.cursor() as cur:
        cur.execute(
            "select id, scoring_settings from public.seasons where year = %s", (year,)
        )
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"no season row for year {year}")
    season_id, scoring_settings = row
    if not scoring_settings:
        raise ValueError("seasons.scoring_settings is empty; run ug sleeper sync first")
    return season_id, scoring_settings


def cmd_projections(args: argparse.Namespace) -> int:
    """Sync one week of projections and the team totals derived from them.

    The fetch happens first and outside the transaction: a thin payload is the
    likeliest failure here, and it should abort before anything is written rather
    than roll back a half-done week. The player rows, the team-week rows, and the
    coverage stamp then land in one `conn.transaction()`, so nothing downstream
    can read team totals computed from a different run's player rows.

    The ops notes are posted after the transaction closes, never inside it: a note
    about numbers that were then rolled back would be a lie in the channel.
    """
    deps = build_deps()
    conn = deps.conn
    now = datetime.now(UTC)
    client = SleeperClient(httpx.Client())

    def action(run_id: int) -> int:
        state = current_week(client, conn, now)
        if state.season_type != "regular":
            # `week` restarts inside each season type, so a preseason 2 is not week
            # 2 of the season. There is no regular-season slate to project, and
            # writing these numbers would look exactly like a real week downstream.
            # A refusal is a non-zero exit, so the transition notes say it once and
            # then go quiet for the rest of the preseason; under `--quiet` the line
            # is not printed either, so cron delivers nothing every half hour.
            if not args.quiet:
                print(
                    f"projections: nfl_state is in the {state.season_type} season, "
                    "not the regular season; nothing to project"
                )
            return 2
        week = args.week if args.week is not None else state.week
        season_id, scoring_settings = _season_row(conn, state.season)
        version = scoring_version(scoring_settings)
        # Outside the transaction on purpose -- see the docstring.
        fetched = None if args.rescore else fetch_projection_rows(client, state.season, week, now)

        repo = ProjectionRepository(conn)
        with conn.transaction():
            if fetched is None:
                report = repo.rescore(state.season, week, scoring_settings, version, now)
            else:
                report = repo.upsert_many(
                    state.season, week, fetched, scoring_settings, version, now
                )
            rows, run_pct = recompute_team_week(conn, season_id, state.season, week, now)
            repo.flag_coverage(
                state.season, week, run_pct, flagged=run_pct < COVERAGE_GATE
            )

        if run_pct < COVERAGE_GATE:
            provisional = sum(1 for r in rows if r.is_provisional)
            deps.notifier.ops(
                f"projections week {week}: coverage {run_pct}% is below "
                f"{COVERAGE_GATE}%; {provisional} teams marked provisional"
            )
        if report.drift_flagged:
            deps.notifier.ops(
                f"projections week {week}: {report.drift_share * Decimal(100):.1f}% of "
                f"scored players differ from the nearest Sleeper preset by more than "
                f"{DRIFT_POINTS} points; check seasons.scoring_settings"
            )
        if not args.quiet:
            print(
                f"projections: week {week}, {report.rows} players "
                f"({report.unscored} unscored), coverage {run_pct}%"
            )
        return 0

    return run_scheduled_with_notes(deps, "projections-sync", now, action)
