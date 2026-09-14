"""Silent live odds refresh, deterministic replay, and historical evaluation."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from ultimate_guillotine.cli.deps import run_scheduled
from ultimate_guillotine.config import load_settings
from ultimate_guillotine.data.database import connect
from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.scoring import scoring_version
from ultimate_guillotine.summary.agent import build_packet
from ultimate_guillotine.summary.distributions import parameters
from ultimate_guillotine.summary.evaluation import load_evaluation
from ultimate_guillotine.summary.replay import replay
from ultimate_guillotine.summary.snapshot import load_snapshot
from ultimate_guillotine.summary.store import SummaryRepository, results_payload


def register(subparsers):
    parser = subparsers.add_parser("odds", help="Live Monte Carlo and forecast evaluation")
    commands = parser.add_subparsers(dest="command", required=True)
    refresh = commands.add_parser("refresh", help="Store current odds; sends no messages")
    refresh.add_argument("--quiet", action="store_true")
    refresh.add_argument("--dry-run", action="store_true")
    refresh.set_defaults(handler=cmd_refresh)
    replay_parser = commands.add_parser("replay")
    replay_parser.add_argument("snapshot_id", type=int)
    replay_parser.set_defaults(handler=cmd_replay)
    evaluate = commands.add_parser(
        "evaluate", help="Evaluate earliest forecasts against final weeks"
    )
    evaluate.add_argument("--out", type=Path)
    evaluate.set_defaults(handler=cmd_evaluate)
    train = commands.add_parser("train", help="Fit 2024, check 2025, save a candidate model file")
    train.add_argument("--cache", type=Path, required=True)
    train.add_argument("--out", type=Path, required=True)
    train.set_defaults(handler=cmd_train)


def cmd_refresh(args):
    now = datetime.now(UTC)
    with connect(load_settings()) as conn, httpx.Client(timeout=20) as http:
        if args.dry_run:
            conn.execute("set transaction read only")

        def action(_run_id):
            state = conn.execute("select season_type from public.nfl_state where id=1").fetchone()
            if not state or state[0] != "regular":
                return 0
            snapshot = load_snapshot(conn, SleeperClient(http), now)
            if snapshot.phase.kind == "over":
                return 0
            config = conn.execute(
                "select scoring_settings from public.seasons where id=%s", (snapshot.season_id,)
            ).fetchone()[0]
            if scoring_version(config) != parameters()["scoring_version"]:
                raise ValueError("Scoring settings changed; refit dispersion parameters")
            if any(
                t.scores_synced_at is None or (now - t.scores_synced_at).total_seconds() > 180
                for t in snapshot.live_teams()
            ):
                raise ValueError("Scores too old for live odds")
            packet = build_packet(snapshot)
            if packet.result is None:
                raise ValueError(packet.no_odds_reason or "Odds unavailable")
            result = packet.result
            if not args.dry_run:
                # Bucketed evidence keeps the source timestamp honest even when the
                # inputs are identical across repeated checks between games.
                SummaryRepository(conn).record_snapshot(
                    snapshot.season_id,
                    snapshot.week,
                    f"live:{now:%Y%m%dT%H%M}",
                    snapshot,
                    result,
                    now,
                )
            if not args.quiet:
                print(
                    json.dumps(
                        {
                            "as_of": now.isoformat(),
                            "model": result.model_version,
                            "teams": results_payload(snapshot, result),
                        }
                    )
                )
            return 0

        if args.dry_run:
            return action(None)
        return run_scheduled(conn, "live-odds", now, action) or 0


def cmd_replay(args):
    with connect(load_settings()) as conn:
        conn.execute("set transaction read only")
        row = conn.execute(
            "select inputs,results,input_hash from public.survival_snapshots where id=%s",
            (args.snapshot_id,),
        ).fetchone()
        if not row or not row[0]:
            raise ValueError("Snapshot has no replayable inputs")
        result = replay(row[0])
        from ultimate_guillotine.summary.replay import decode

        matches = result.input_hash == row[2] and results_payload(decode(row[0]), result) == row[1]
        print(
            json.dumps(
                {"snapshot_id": args.snapshot_id, "matches": matches, "seed": str(result.seed)}
            )
        )
        return 0 if matches else 1


def cmd_evaluate(args):
    with connect(load_settings()) as conn:
        conn.execute("set transaction read only")
        report = load_evaluation(conn)
    text = json.dumps(report, indent=2, default=str) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    else:
        print(text)
    return 0


def cmd_train(args):
    from ultimate_guillotine.summary.training import train

    with connect(load_settings()) as conn:
        conn.execute("set transaction read only")
        scoring = conn.execute(
            "select scoring_settings from public.seasons order by year desc limit 1"
        ).fetchone()[0]
    report = train(scoring, args.cache, args.out)
    print(json.dumps(report["holdout"], indent=2))
    return 0
