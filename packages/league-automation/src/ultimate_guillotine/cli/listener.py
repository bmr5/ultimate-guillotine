"""`ug listener` subcommands."""

import argparse

from ultimate_guillotine.listener.run import main as run_listener


def register(subparsers) -> None:
    parser = subparsers.add_parser("listener", help="webhook listener commands")
    listener_sub = parser.add_subparsers(dest="command", required=True)

    run_parser = listener_sub.add_parser("run", help="run the BlueBubbles webhook listener")
    run_parser.set_defaults(handler=cmd_run)


def cmd_run(args: argparse.Namespace) -> int:
    run_listener()
    return 0
