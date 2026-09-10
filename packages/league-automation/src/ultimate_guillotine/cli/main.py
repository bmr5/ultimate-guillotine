"""Entry point for the `ug` command-line tool.

`ug` wraps every operation Hermes cron jobs and the Mac mini operator need:
health checks, run auditing, delivery targets, Sleeper sync, message
ingestion catch-up, and the webhook listener itself.
"""

import argparse
import sys

from ultimate_guillotine.cli import (
    advisor,
    archive,
    history,
    ingest,
    listener,
    members,
    ops,
    sleeper,
    summary,
    targets,
    trades,
    video,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ug", description="Ultimate Guillotine automation CLI")
    subparsers = parser.add_subparsers(dest="group", required=True)
    for module in (
        ops,
        targets,
        sleeper,
        ingest,
        listener,
        trades,
        members,
        advisor,
        archive,
        history,
        summary,
        video,
    ):
        module.register(subparsers)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        exit_code = args.handler(args)
    except Exception as exc:  # noqa: BLE001 - last-resort guard, never a traceback
        command = f"{args.group} {args.command}"
        print(f"ug {command} failed: {exc.__class__.__name__}", file=sys.stderr)
        sys.exit(1)
    sys.exit(exit_code or 0)


if __name__ == "__main__":
    main()
