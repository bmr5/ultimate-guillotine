"""`ug trades` subcommands: extract, list, retry, replay.

``extract`` is the safe one: it runs the whole pipeline except the writes and
the send, so a prompt or resolution change can be checked against a real
announcement without touching the league. ``retry`` is the opposite -- it
re-runs a candidate for real, from the excerpt already recorded for it.
"""

import argparse
from datetime import UTC, datetime

import httpx

from ultimate_guillotine.cli.deps import build_ai, build_delivery, build_deps
from ultimate_guillotine.data.repositories import (
    MemberAliasRepository,
    RunRepository,
    SourceMessageRepository,
)
from ultimate_guillotine.messages.bluebubbles import InboundMessage
from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.players import PlayerRepository
from ultimate_guillotine.trades.extract import PROMPT_VERSION, extract_trade
from ultimate_guillotine.trades.registrar import TradeRegistrar
from ultimate_guillotine.trades.repository import TradeRepository
from ultimate_guillotine.trades.resolve import (
    RosterIndex,
    Unresolved,
    build_roster_index,
    resolve_extracted,
    validate,
)


def register(subparsers) -> None:
    parser = subparsers.add_parser("trades", help="trade registrar commands")
    trades_sub = parser.add_subparsers(dest="command", required=True)

    extract = trades_sub.add_parser(
        "extract", help="dry-run one announcement through the registrar; writes and sends nothing"
    )
    extract.add_argument("--text", required=True, help="the announcement to extract")
    extract.add_argument(
        "--rosters",
        action="store_true",
        help="fetch live Sleeper rosters to disambiguate duplicate names",
    )
    extract.set_defaults(handler=cmd_extract)

    listing = trades_sub.add_parser("list", help="show the most recently logged trades")
    listing.add_argument("--limit", type=int, default=10)
    listing.set_defaults(handler=cmd_list)

    retry = trades_sub.add_parser("retry", help="re-run a recorded candidate through the registrar")
    retry.add_argument("source_guid")
    retry.set_defaults(handler=cmd_retry)

    replay = trades_sub.add_parser("replay", help="replay a season of trades from a spreadsheet")
    replay.add_argument("xlsx")
    replay.add_argument("--limit", type=int, default=None)
    replay.add_argument("--dry-run", action="store_true")
    replay.set_defaults(handler=cmd_replay)


def cmd_extract(args: argparse.Namespace) -> int:
    """Print what the registrar would record, without recording or sending it."""
    deps = build_deps()
    conn = deps.conn
    members = MemberAliasRepository(conn).all_members()
    member_names = [
        f"{m.display_name}: {', '.join(m.aliases) or 'no known nicknames'}" for m in members
    ]
    season = datetime.now(UTC).year
    extracted, usage = extract_trade(build_ai(deps), args.text, season, None, member_names)
    if extracted.kind == "not_a_trade":
        print("not a trade")
        return 0
    rosters = (
        build_roster_index(SleeperClient(httpx.Client()), conn, deps.settings.sleeper_league_id)
        if args.rosters
        else RosterIndex.empty()
    )
    try:
        proposal = resolve_extracted(
            extracted,
            members,
            PlayerRepository(conn).all_active(),
            rosters,
            season,
            "dry-run",
            args.text[:2000],
            PROMPT_VERSION,
            usage.model,
        )
        validate(proposal)
    except Unresolved as exc:
        print(f"clarification: {exc.reason}")
        return 0
    print(proposal.model_dump_json(indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    deps = build_deps()
    for trade in TradeRepository(deps.conn).list_recent(args.limit):
        parties = ", ".join(
            p.get("display_name", "?") for p in (trade["terms"] or {}).get("parties", [])
        )
        week = trade["effective_week"] if trade["effective_week"] is not None else "-"
        print(f"{trade['trade_code']}  {trade['status']}  {trade['revision']}  {week}  {parties}")
    return 0


def cmd_retry(args: argparse.Namespace) -> int:
    """Re-run one recorded candidate, for real.

    The raw chat GUID and sender address were never stored, so the message is
    rebuilt from the excerpt with the configured test chat and no sender. The
    per-attempt idempotency key is what makes this work at all: the original
    attempt already holds ``trade:<guid>``.
    """
    deps = build_deps()
    conn = deps.conn
    source = SourceMessageRepository(conn).get(args.source_guid)
    if source is None or not source.excerpt:
        print(f"no recorded message for {args.source_guid}")
        return 1
    msg = InboundMessage(
        guid=source.source_guid,
        chat_guid=deps.settings.test_chat_guid or "",
        sender_address=None,
        text=source.excerpt,
        is_from_me=False,
        is_group=True,
        sent_at=source.sent_at,
    )
    registrar = TradeRegistrar(
        deps.settings,
        conn,
        build_ai(deps),
        build_delivery(deps),
        deps.notifier,
        MemberAliasRepository(conn),
        PlayerRepository(conn),
        TradeRepository(conn),
        RunRepository(conn),
        sleeper_client=SleeperClient(httpx.Client()),
    )
    status = registrar.handle(msg, retry=True)
    print(f"retry: {status}")
    # A failed retry has to be visible to whatever re-ran it, not just printed.
    return 1 if status == "failed" else 0


def cmd_replay(args: argparse.Namespace) -> int:
    print("replay is implemented in Task 9")
    return 0
