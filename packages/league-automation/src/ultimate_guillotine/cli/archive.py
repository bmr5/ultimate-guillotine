"""`ug archive`: automatic collection and deterministic weekly history, without messaging."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from ultimate_guillotine.cli.deps import build_deps, run_scheduled
from ultimate_guillotine.history.archive_jobs import capture_current, configuration, enable, tick
from ultimate_guillotine.history.archive_store import rows
from ultimate_guillotine.sleeper.client import SleeperClient


class Ruling(BaseModel):
    model_config = ConfigDict(extra="forbid")
    week: int = Field(ge=1, le=17)
    actor: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=1000)
    substitutions: dict[int, int] = {}
    tie_order: list[int] = []
    reviewed_trade_codes: list[str] = []


def register(subparsers):
    parser = subparsers.add_parser("archive", help="2026 gulag and elimination archive")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("capture", "tick", "status"):
        p = sub.add_parser(name)
        p.add_argument("--quiet", action="store_true")
        p.set_defaults(handler=cmd_archive)
    p = sub.add_parser("enable", help="enable the reviewed 2026 capture/adjudication jobs")
    p.add_argument("--season", type=int, default=2026)
    p.add_argument("--scope", choices=("production", "test"), required=True)
    p.set_defaults(handler=cmd_archive, quiet=False)
    p = sub.add_parser("ruling", help="record an explicit commissioner ruling from a JSON file")
    p.add_argument("--file", type=Path, required=True)
    p.set_defaults(handler=cmd_archive, quiet=False)


def record_ruling(conn, config: dict, ruling: Ruling, now: datetime):
    teams = {
        t["id"]
        for t in rows(
            conn, "select id from public.teams where season_id=%s", (config["season_id"],)
        )
    }
    supplied = (
        set(ruling.substitutions) | set(ruling.substitutions.values()) | set(ruling.tie_order)
    )
    if not supplied <= teams or len(ruling.tie_order) != len(set(ruling.tie_order)):
        raise ValueError("ruling contains unknown or repeated team identities")
    if ruling.substitutions and not 2 <= ruling.week <= 12:
        raise ValueError("substitutions require a gulag contest week, 2 through 12")
    reviewed = {}
    for code in ruling.reviewed_trade_codes:
        found = rows(
            conn,
            """select current_revision_id from public.trades
            where season_id=%s and trade_code=%s and status='accepted'""",
            (config["season_id"], code),
        )
        if not found or (config["scope"] == "production" and code.startswith("TEST-")):
            raise ValueError("reviewed agreements must be accepted, non-test trades")
        reviewed[code] = found[0]["current_revision_id"]
    payload = ruling.model_dump(mode="json", exclude={"actor", "reason", "week"})
    payload["reviewed_trade_revisions"] = reviewed
    with conn.transaction():
        conn.execute("select pg_advisory_xact_lock(82426,%s)", (config["season_id"],))
        result = conn.execute(
            """insert into private.archive_rulings
            (season_id,scope,week,actor,reason,recorded_at,payload) values (%s,%s,%s,%s,%s,%s,%s)
            returning id""",
            (
                config["season_id"],
                config["scope"],
                ruling.week,
                ruling.actor,
                ruling.reason,
                now,
                Jsonb(payload),
            ),
        ).fetchone()[0]
        conn.execute(
            """update private.archive_week_jobs set next_check_at=%s,
            candidate_hash=null,stable_since=null where season_id=%s and scope=%s and week=%s""",
            (now, config["season_id"], config["scope"], ruling.week),
        )
    return result


def cmd_archive(args: argparse.Namespace):
    deps = build_deps()
    now = datetime.now(UTC)
    with httpx.Client() as http:
        client = SleeperClient(http)
        if args.command == "enable":
            season_id = enable(
                deps.conn, client, deps.settings.sleeper_league_id, args.season, args.scope, now
            )
            deps.conn.commit()
            print(f"Archive enabled: season {args.season}, {args.scope}, id {season_id}")
            return 0
        if args.command == "status":
            config = configuration(deps.conn)
            if not config:
                print("Archive is not enabled.")
                return 0
            print(
                f"Season {config['season']} · {config['scope']} · last capture {config['last_capture_at']}"
            )
            for job in rows(
                deps.conn,
                """select week,status,next_check_at,last_error
                from private.archive_week_jobs where season_id=%s and scope=%s order by week""",
                (config["season_id"], config["scope"]),
            ):
                print(
                    f"Week {job['week']}: {job['status']}; next {job['next_check_at']}; {job['last_error'] or 'no exception'}"
                )
            return 0
        if args.command == "ruling":
            config = configuration(deps.conn)
            if not config:
                raise ValueError("enable the archive before recording a ruling")
            ruling_id = record_ruling(
                deps.conn, config, Ruling.model_validate_json(args.file.read_text()), now
            )
            deps.conn.commit()
            print(
                f"Commissioner ruling {ruling_id} recorded; the next tick will re-evaluate the week."
            )
            return 0

        def action(_run_id):
            result = (
                capture_current(deps.conn, client, now)
                if args.command == "capture"
                else tick(deps.conn, client, now)
            )
            if not args.quiet:
                print(json.dumps(result))
            return 0

        return run_scheduled(deps.conn, f"archive-{args.command}", now, action)
