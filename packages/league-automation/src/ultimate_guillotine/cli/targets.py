"""`ug targets` subcommands."""

import argparse

from ultimate_guillotine.cli.deps import build_deps
from ultimate_guillotine.config import DeliveryMode
from ultimate_guillotine.data.repositories import TargetRepository
from ultimate_guillotine.messages.fingerprint import participant_fingerprint


def register(subparsers) -> None:
    parser = subparsers.add_parser("targets", help="delivery target commands")
    targets_sub = parser.add_subparsers(dest="command", required=True)

    set_parser = targets_sub.add_parser("set", help="store the delivery target for a mode")
    set_parser.add_argument("--mode", choices=["test", "production"], required=True)
    set_parser.add_argument("--chat-guid", required=True)
    set_parser.add_argument("--label", required=True)
    set_parser.set_defaults(handler=cmd_set)


def cmd_set(args: argparse.Namespace) -> int:
    deps = build_deps()
    mode = DeliveryMode(args.mode)
    fingerprint = None
    if mode is DeliveryMode.PRODUCTION:
        fingerprint = participant_fingerprint(deps.client.chat_participants(args.chat_guid))
    target_id = TargetRepository(deps.conn).upsert(mode, args.chat_guid, fingerprint, args.label)
    deps.conn.commit()
    print(target_id)
    return 0
