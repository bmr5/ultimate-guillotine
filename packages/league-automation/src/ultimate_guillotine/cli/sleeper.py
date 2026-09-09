"""`ug sleeper` subcommands."""

import argparse
from datetime import UTC, datetime

import httpx

from ultimate_guillotine.cli.deps import build_deps, run_scheduled
from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.players import sync_players
from ultimate_guillotine.sleeper.state import current_week, sync_nfl_state
from ultimate_guillotine.sleeper.sync import sync_season

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
                f"{report.holdings} holdings, {report.states} team states"
            )
        return 0

    return run_scheduled(conn, "sleeper-sync", now, action)


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

    return run_scheduled(conn, "nfl-state", now, action)
