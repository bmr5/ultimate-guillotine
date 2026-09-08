"""Entry point for the `ug` command-line tool.

`ug` wraps every operation Hermes cron jobs and the Mac mini operator need:
health checks, run auditing, delivery targets, Sleeper sync, message
ingestion catch-up, and the webhook listener itself.
"""

import argparse
import sys

from ultimate_guillotine.cli import ingest, listener, ops, sleeper, targets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ug", description="Ultimate Guillotine automation CLI")
    subparsers = parser.add_subparsers(dest="group", required=True)
    for module in (ops, targets, sleeper, ingest, listener):
        module.register(subparsers)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.handler(args) or 0)


if __name__ == "__main__":
    main()
