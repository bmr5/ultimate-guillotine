"""`ug agent`: the League Agent's tool server, dry run, and answer log."""

import argparse

from ultimate_guillotine.agent.tools.mcp import serve


def register(subparsers) -> None:
    parser = subparsers.add_parser("agent", help="League Agent commands")
    agent_sub = parser.add_subparsers(dest="command", required=True)
    mcp = agent_sub.add_parser(
        "mcp", help="serve the league's read-only tools over stdio for the Hermes profile"
    )
    mcp.add_argument(
        "--fixture", action="store_true",
        help="serve the fixture league instead of the database (also UG_AGENT_FIXTURE=1)",
    )
    mcp.set_defaults(handler=cmd_mcp)


def cmd_mcp(args: argparse.Namespace) -> int:
    return serve(args.fixture)
