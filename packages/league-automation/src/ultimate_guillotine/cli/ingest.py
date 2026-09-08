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
GAP_FILL_PAGE_SIZE = 100
MAX_GAP_FILL_PAGES = 20
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


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
            # `latest_sent_at` only sees messages that already qualified for a trigger,
            # so it can sit days in the past. Floor the window at --since-minutes so a
            # replay stays bounded instead of walking the whole chat history.
            latest = sources.latest_sent_at(chat_guid_hash(guid)) or EPOCH
            cursor = max(latest, now - timedelta(minutes=args.since_minutes))
            for _page in range(MAX_GAP_FILL_PAGES):
                batch = deps.client.messages_after(guid, cursor, limit=GAP_FILL_PAGE_SIZE)
                for msg in batch:
                    outcome = processor.process(msg, msg.guid)
                    total += 1
                    if outcome.startswith("handled"):
                        handled += 1
                # A short page is the end of the chat; a full one may not be.
                if len(batch) < GAP_FILL_PAGE_SIZE:
                    break
                cursor = batch[-1].sent_at + timedelta(milliseconds=1)
        print(f"gap-fill: {total} messages, {handled} handled")
        return 0

    return run_scheduled(conn, "gap-fill", now, action)
