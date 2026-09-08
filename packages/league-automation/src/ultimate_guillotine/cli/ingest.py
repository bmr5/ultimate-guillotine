"""`ug ingest` subcommands."""

import argparse
from datetime import UTC, datetime, timedelta

from ultimate_guillotine.cli.deps import build_delivery, build_deps, run_scheduled
from ultimate_guillotine.data.repositories import (
    SourceMessageRepository,
    chat_guid_hash,
)
from ultimate_guillotine.listener.run import build_processor

DEFAULT_SINCE_MINUTES = 60


def register(subparsers) -> None:
    parser = subparsers.add_parser("ingest", help="message ingestion commands")
    ingest_sub = parser.add_subparsers(dest="command", required=True)

    gap_fill = ingest_sub.add_parser(
        "gap-fill", help="replay missed messages through the trigger pipeline"
    )
    gap_fill.add_argument("--since-minutes", type=int, default=DEFAULT_SINCE_MINUTES)
    gap_fill.set_defaults(handler=cmd_gap_fill)


def cmd_gap_fill(args: argparse.Namespace) -> int:
    deps = build_deps()
    conn = deps.conn
    settings = deps.settings
    now = datetime.now(UTC)

    def action(run_id: int) -> int:
        delivery = build_delivery(deps)
        processor, allowed = build_processor(settings, conn, deps.client, delivery, deps.notifier)
        sources = SourceMessageRepository(conn)
        total = handled = 0
        for guid in allowed:
            since = sources.latest_sent_at(chat_guid_hash(guid)) or (
                now - timedelta(minutes=args.since_minutes)
            )
            for msg in deps.client.messages_after(guid, since):
                outcome = processor.process(msg, msg.guid)
                total += 1
                if outcome.startswith("handled"):
                    handled += 1
        print(f"gap-fill: {total} messages, {handled} handled")
        return 0

    return run_scheduled(conn, "gap-fill", now, action)
