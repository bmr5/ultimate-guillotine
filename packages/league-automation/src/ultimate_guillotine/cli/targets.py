"""`ug targets` subcommands.

Two kinds of registration live here, and the difference between them is the whole
of shadow mode:

``set`` records the one chat a delivery mode posts to. ``listen`` records a chat
the listener *processes messages from* and never posts to -- the league chat,
while ``DELIVERY_MODE`` is still ``test``, so a real trade alert reaches the
Registrar and its answer comes back in the self-test chat with a ``TEST-`` code.

Neither command ever prints a chat GUID. ``set`` takes one because it has to
(the delivery target's identity is checked against it) and answers with a row
id; ``listen`` takes it from ``PRODUCTION_CHAT_GUID`` in the environment unless
one is passed, and answers with a count. A GUID that reaches the terminal reaches
the scrollback, and this is a private group chat.
"""

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

    listen = targets_sub.add_parser(
        "listen",
        help="register a chat the listener reads and never posts to (shadow mode)",
    )
    listen.add_argument(
        "--chat-guid",
        default=None,
        help="the chat to listen in; defaults to PRODUCTION_CHAT_GUID from the environment",
    )
    listen.add_argument("--label", required=True, help="what to call this chat in the table")
    listen.set_defaults(handler=cmd_listen)

    counts = targets_sub.add_parser("counts", help="how many targets of each role are registered")
    counts.set_defaults(handler=cmd_counts)


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


def cmd_listen(args: argparse.Namespace) -> int:
    """Register one chat as listen-only, and say how many there now are.

    With no ``--chat-guid`` the league chat is taken from ``PRODUCTION_CHAT_GUID``,
    which is the case this command exists for and the one where nobody should have
    to paste a GUID at a prompt. Nothing is printed but a count: not the GUID, not
    its hash, not the label of any other row.

    No participant fingerprint is recorded. That check exists to stop the bot
    posting into a chat whose membership changed underneath it, and a listen-only
    chat is never posted to.
    """
    deps = build_deps()
    chat_guid = args.chat_guid or deps.settings.production_chat_guid
    if not chat_guid:
        print("no chat to listen in: pass --chat-guid or set PRODUCTION_CHAT_GUID")
        return 2
    targets = TargetRepository(deps.conn)
    targets.upsert_listen(chat_guid, args.label)
    deps.conn.commit()
    print(f"listen-only chats registered: {len(targets.listen_chat_guids())}")
    return 0


def cmd_counts(args: argparse.Namespace) -> int:
    """Say what is registered, in counts only -- never which chats."""
    deps = build_deps()
    targets = TargetRepository(deps.conn)
    for mode in (DeliveryMode.TEST, DeliveryMode.PRODUCTION):
        print(f"{mode.value} delivery target: {'yes' if targets.get(mode) else 'no'}")
    print(f"listen-only chats registered: {len(targets.listen_chat_guids())}")
    return 0
