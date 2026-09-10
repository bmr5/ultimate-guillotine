"""`ug summary eod`: compose tonight's summary and post it -- or only print it.

The scheduled path is the whole agent under ``run_scheduled_with_notes``: one run
row under the ``eod-summary`` agent, one ops note on the edge when a night fails,
and the post itself -- a short text, then the HTML file -- through the delivery
layer. The dry run is the same composition with nothing to write through:
``--dry-run`` reads the real league, prints the chat text, writes the file to
``--out`` and prints its path, records no run, posts nowhere; ``--json`` prints
the fact packet -- every team's line and odds -- and makes no model call;
``--fixture`` answers out of the closed-form league so the shape can be checked
on a machine with no database, no Sleeper and no Hermes at all.

The colour is opportunistic on every path. No Hermes on the machine is one ops
note (or one stderr line) and a message without colour, never a failed run: the
deterministic summary is the deliverable and the model is the garnish.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from ultimate_guillotine.agent.tools.snapshot import SnapshotUnavailable
from ultimate_guillotine.ai.structured import AIUnavailable
from ultimate_guillotine.cli.deps import (
    build_delivery,
    build_deps,
    post_ops,
    run_scheduled_with_notes,
)
from ultimate_guillotine.config import Settings, load_settings
from ultimate_guillotine.core.hermes_cli import find_hermes_binary
from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.state import current_week
from ultimate_guillotine.summary.agent import (
    AGENT,
    EodSummaryAgent,
    build_packet,
    compose_summary,
)
from ultimate_guillotine.summary.color import color_client
from ultimate_guillotine.summary.fixture import FIXTURE_NOW, fixture_eod
from ultimate_guillotine.summary.models import EodPacket, EodSnapshot
from ultimate_guillotine.summary.phase import phase_kind
from ultimate_guillotine.summary.snapshot import load_snapshot
from ultimate_guillotine.summary.store import SummaryRepository
from ultimate_guillotine.summary.survival import DEFAULT_SIMULATIONS

NO_HERMES = "hermes CLI not found"


def register(subparsers) -> None:
    parser = subparsers.add_parser("summary", help="league summary posts")
    summary_sub = parser.add_subparsers(dest="command", required=True)
    eod = summary_sub.add_parser("eod", help="compose and post tonight's end-of-day summary")
    eod.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="print the message; write nothing, send nothing, record no run",
    )
    eod.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="print the fact packet the message is built from; makes no model call",
    )
    eod.add_argument(
        "--fixture",
        action="store_true",
        help="answer out of the fixture league; needs no database (implies --dry-run)",
    )
    eod.add_argument("--no-ai", dest="no_ai", action="store_true", help="skip the colour")
    eod.add_argument("--seed", type=int, default=None, help="fix the simulation seed")
    eod.add_argument(
        "--simulations", type=int, default=DEFAULT_SIMULATIONS, help="how many simulations"
    )
    eod.add_argument(
        "--force",
        action="store_true",
        help="post again even if tonight's summary already went out",
    )
    eod.add_argument(
        "--out",
        default=".",
        help="where a dry run writes the HTML file (default: the current directory)",
    )
    eod.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing on success so a scheduled run delivers only failures",
    )
    eod.set_defaults(handler=cmd_eod)


class StderrNotifier:
    """The dry run's ops channel: the terminal it was typed into."""

    def ops(self, text: str) -> bool:
        print(text, file=sys.stderr)
        return True

    drafts = ops
    alerts = ops


class LazyClient:
    """The colour's client, built by the first call that needs one.

    Built late so a dry run with ``--json`` or a rejected colour never needs the
    Hermes CLI or a configured league. A missing CLI, or settings that cannot be
    loaded on a machine with no league, surface as ``AIUnavailable`` -- which the
    composer reads as "no colour tonight", exactly as it reads a Hermes outage.
    """

    def __init__(self, settings: Settings | None) -> None:
        self._settings = settings
        self._client = None

    def parse(self, system: str, user: str, schema, schema_name: str):
        if self._client is None:
            if find_hermes_binary() is None:
                raise AIUnavailable(NO_HERMES)
            try:
                settings = self._settings or load_settings()
            except (ValueError, OSError) as exc:
                raise AIUnavailable("no settings to read a Hermes profile from") from exc
            self._client = color_client(settings.hermes_profile_home, model=settings.hermes_model)
        return self._client.parse(system, user, schema, schema_name)


def _decimal(value) -> str | None:
    return None if value is None else str(value)


def packet_json(packet: EodPacket) -> dict:
    """The packet as an operator reads it: every team, every starter, every number."""
    snap, result = packet.snapshot, packet.result
    teams = []
    for team in snap.teams:
        odds = result.teams.get(team.team_id) if result is not None else None
        teams.append(
            {
                "team_id": team.team_id,
                "label": team.label,
                "team_name": team.team_name,
                "is_eliminated": team.is_eliminated,
                "eliminated_week": team.eliminated_week,
                "faab_remaining": team.faab_remaining,
                "points": str(team.points),
                "has_score_row": team.has_score_row,
                "pending": len(team.pending()),
                "empty_slots": team.empty_slots(),
                "out_starters": [f"{s.name} ({s.injury_status})" for s in team.out_starters()],
                "unprojected_pending": [s.name for s in team.unprojected_pending()],
                "projected_final": None if odds is None else str(odds.projected_final),
                "probability": None if odds is None else str(odds.probability),
                "adverse_event": None if odds is None else odds.adverse_event,
                "is_estimated": None if odds is None else odds.is_estimated,
                "starters": [
                    {
                        "name": s.name,
                        "position": s.position,
                        "slot": s.lineup_position,
                        "nfl_team": s.nfl_team,
                        "injury_status": s.injury_status,
                        "status": s.status,
                        "projected": _decimal(s.projected),
                        "points": str(s.points),
                    }
                    for s in team.starters
                ],
            }
        )
    body: dict = {
        "season": snap.season,
        "week": snap.week,
        "day_state": snap.day_state,
        "games_final": snap.games_final,
        "games_total": snap.games_total,
        "schedule_available": snap.schedule_available,
        "phase": {
            "kind": snap.phase.kind,
            "gulag_team_ids": list(snap.phase.gulag_team_ids),
            "gulag_source": snap.phase.gulag_source,
        },
        "coverage_pct": str(packet.coverage_pct),
        "no_odds_reason": packet.no_odds_reason,
        "moves": [
            {
                "kind": m.kind,
                "team": m.team_label,
                "adds": list(m.adds),
                "drops": list(m.drops),
                "waiver_bid": m.waiver_bid,
            }
            for m in snap.moves
        ],
        "teams": teams,
    }
    if result is not None:
        body.update(
            simulations=result.simulations,
            seed=result.seed,
            input_hash=result.input_hash,
            model_version=result.model_version,
        )
    return body


def _dry_run(
    snapshot: EodSnapshot, now: datetime, settings: Settings | None, args: argparse.Namespace
) -> int:
    """Compose and print, into the terminal and nowhere else."""
    if phase_kind(snapshot.week) == "over":
        print("eod: skipped, season over")
        return 0
    if args.as_json:
        packet = build_packet(snapshot, simulations=args.simulations, seed=args.seed)
        print(json.dumps(packet_json(packet), indent=2))
        return 0
    composed = compose_summary(
        snapshot,
        now,
        ai=None if args.no_ai else LazyClient(settings),
        notifier=StderrNotifier(),
        use_ai=not args.no_ai,
        simulations=args.simulations,
        seed=args.seed,
    )
    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact = out_dir / composed.filename
    artifact.write_text(composed.html, encoding="utf-8")
    print(composed.short)
    print()
    print(f"artifact: {artifact.resolve()}")
    return 0


def cmd_eod(args: argparse.Namespace) -> int:
    if args.fixture:
        return _dry_run(fixture_eod(), FIXTURE_NOW, None, args)

    deps = build_deps()
    conn = deps.conn
    now = datetime.now(UTC)
    client = SleeperClient(httpx.Client())

    if args.dry_run or args.as_json:
        state = current_week(client, conn, now)
        if state.season_type != "regular":
            print(f"eod: skipped, season_type={state.season_type}")
            return 0
        try:
            snapshot = load_snapshot(conn, client, now)
        except SnapshotUnavailable as exc:
            print(f"no snapshot: {exc.reason}", file=sys.stderr)
            return 1
        return _dry_run(snapshot, now, deps.settings, args)

    def action(run_id: int) -> int:
        state = current_week(client, conn, now)
        if state.season_type != "regular":
            # `week` restarts inside each season type, and there is no slate to
            # summarise outside the regular one. Not a failure: the nightly fire
            # stays green all winter.
            if not args.quiet:
                print(f"eod: skipped, season_type={state.season_type}")
            return 0
        if phase_kind(state.week) == "over":
            if not args.quiet:
                print("eod: skipped, season over")
            return 0
        try:
            snapshot = load_snapshot(conn, client, now)
        except SnapshotUnavailable as exc:
            # The one reason that is an operational answer rather than a message:
            # said plainly, and the run is recorded failed so the ops note fires.
            print(f"no snapshot: {exc.reason}", file=sys.stderr)
            return 1

        ai = None
        if not args.no_ai:
            if find_hermes_binary() is None:
                post_ops(deps.notifier, f"EOD summary colour disabled: {NO_HERMES}")
            else:
                ai = color_client(
                    deps.settings.hermes_profile_home, model=deps.settings.hermes_model
                )
        agent = EodSummaryAgent(
            deps.settings,
            conn,
            ai,
            build_delivery(deps),
            deps.notifier,
            SummaryRepository(conn),
        )
        outcome = agent.run(
            snapshot,
            now,
            run_id=run_id,
            use_ai=not args.no_ai,
            force=args.force,
            simulations=args.simulations,
            seed=args.seed,
        )
        if not args.quiet:
            print(
                f"eod: {outcome.status}, week {snapshot.week}, "
                f"odds {'yes' if outcome.odds else 'no'}, model {outcome.model or 'none'}"
            )
        return 0

    return run_scheduled_with_notes(deps, AGENT, now, action)
