"""`ug sleeper` subcommands."""

import argparse
from datetime import UTC, datetime

import httpx

from ultimate_guillotine.cli.deps import build_deps, run_scheduled
from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.players import sync_players
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


def cmd_sync(args: argparse.Namespace) -> int:
    deps = build_deps()
    conn = deps.conn
    now = datetime.now(UTC)

    def action(run_id: int) -> int:
        report = sync_season(
            SleeperClient(httpx.Client()), conn, SYNC_YEAR, deps.settings.sleeper_league_id
        )
        if not args.quiet:
            print(f"sleeper sync: {report.members} members, {report.teams} teams")
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
