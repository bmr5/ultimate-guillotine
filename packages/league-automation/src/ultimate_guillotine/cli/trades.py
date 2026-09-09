"""`ug trades` subcommands: extract, list, retry, replay.

``extract`` is the safe one: it runs the whole pipeline except the writes and
the send, so a prompt or resolution change can be checked against a real
announcement without touching the league. ``retry`` is the opposite -- it
re-runs a candidate for real, from the excerpt already recorded for it.
``replay`` is ``extract`` in bulk: a whole season of announcements out of the
contracts spreadsheet, so a prompt change can be measured against real history.
"""

import argparse
import hashlib
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import openpyxl

from ultimate_guillotine.cli.deps import build_ai, build_delivery, build_deps
from ultimate_guillotine.config import DeliveryMode, load_settings
from ultimate_guillotine.data.repositories import (
    MemberAliasRepository,
    RunRepository,
    SeasonRepository,
    SourceMessageRepository,
)
from ultimate_guillotine.messages.bluebubbles import InboundMessage
from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.players import PlayerRepository
from ultimate_guillotine.trades.detect import ALERT, is_trade_candidate
from ultimate_guillotine.trades.extract import PROMPT_VERSION, extract_trade
from ultimate_guillotine.trades.models import TradeProposal
from ultimate_guillotine.trades.registrar import TradeRegistrar
from ultimate_guillotine.trades.repository import TradeRepository, code_prefix_for
from ultimate_guillotine.trades.resolve import (
    RosterIndex,
    Unresolved,
    build_roster_index,
    resolve_extracted,
    validate,
)

#: What the model called a joke rather than a trade. A sentinel rather than a
#: reason string so callers compare identity instead of matching prose.
NOT_A_TRADE = Unresolved("not a trade")

#: Column layout of `history/contracts/<season>/all-contracts.xlsx`:
#: `Date, Week, Terms, Parties...`, with each extra column holding one party.
WEEK_COLUMN = 1
TERMS_COLUMN = 2

#: The season the 2025-26 contract sheet belongs to. Replay names it outright
#: rather than letting the registrar read `public.seasons`, and dates each
#: replayed message from a clock inside that season.
REPLAY_SEASON = 2025
REPLAY_CLOCK = datetime(REPLAY_SEASON, 12, 31, tzinfo=UTC)
REPLAY_START = datetime(REPLAY_SEASON, 9, 1, tzinfo=UTC)

#: Counters the replay summary always prints, even at zero, so the line has a
#: stable shape to read or grep across runs.
SUMMARY_FIXED = ("created", "duplicate", "clarification", "not-a-candidate")

#: The rest of the outcome vocabulary. Printed only when it happened, so the
#: usual summary stays short -- but every row is counted somewhere, so the
#: counters always add up to the row count.
SUMMARY_EXTRA = ("revised", "rescinded", "not-a-trade", "failed", "skipped")


def positive_int(value: str) -> int:
    """An argparse type for counts: `--limit 0` asks for nothing and `--limit -1`
    asks for nonsense, so both are refused at the parser rather than silently
    returning an empty list."""
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or more, not {number}")
    return number


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
    listing.add_argument("--limit", type=positive_int, default=10)
    listing.set_defaults(handler=cmd_list)

    retry = trades_sub.add_parser("retry", help="re-run a recorded candidate through the registrar")
    retry.add_argument("source_guid")
    retry.set_defaults(handler=cmd_retry)

    replay = trades_sub.add_parser(
        "replay",
        help="replay a season of announcements from the contracts spreadsheet",
    )
    replay.add_argument("xlsx", help="path to all-contracts.xlsx")
    replay.add_argument(
        "--limit", type=positive_int, default=None, help="stop after this many rows (default: all)"
    )
    replay.add_argument(
        "--dry-run", action="store_true", help="resolve only; write nothing and send nothing"
    )
    replay.set_defaults(handler=cmd_replay)


def dry_run_pipeline(
    ai,
    text: str,
    season: int,
    members,
    players,
    rosters: RosterIndex,
    source_guid: str = "dry-run",
) -> TradeProposal | Unresolved:
    """Extract, resolve, and validate one announcement without writing or sending.

    Returns the resolved proposal, `NOT_A_TRADE` when the model read the text as
    chatter, or the `Unresolved` that stopped resolution -- whose `reason` is the
    question the registrar would have asked the chat. Nothing here touches the
    database or the delivery service, which is what makes it safe to point at a
    whole season of history.
    """
    member_names = [
        f"{m.display_name}: {', '.join(m.aliases) or 'no known nicknames'}" for m in members
    ]
    extracted, usage = extract_trade(ai, text, season, None, member_names)
    if extracted.kind == "not_a_trade":
        return NOT_A_TRADE
    try:
        proposal = resolve_extracted(
            extracted,
            members,
            players,
            rosters,
            season,
            source_guid,
            text[:2000],
            PROMPT_VERSION,
            usage.model,
        )
        validate(proposal)
    except Unresolved as exc:
        return exc
    return proposal


def cmd_extract(args: argparse.Namespace) -> int:
    """Print what the registrar would record, without recording or sending it."""
    deps = build_deps()
    conn = deps.conn
    # The same season the registrar would record under, so a dry run and the
    # real thing never disagree about which season a name belongs to.
    season = SeasonRepository(conn).current() or datetime.now(UTC).year
    rosters = (
        build_roster_index(
            SleeperClient(httpx.Client()), conn, deps.settings.sleeper_league_id, season
        )
        if args.rosters
        else RosterIndex.empty()
    )
    result = dry_run_pipeline(
        build_ai(deps),
        args.text,
        season,
        MemberAliasRepository(conn).all_members(),
        PlayerRepository(conn).all_active(),
        rosters,
    )
    if result is NOT_A_TRADE:
        print("not a trade")
    elif isinstance(result, Unresolved):
        print(f"clarification: {result.reason}")
    else:
        print(result.model_dump_json(indent=2))
    return 0


#: The columns `print_trades` writes, in order.
LIST_HEADER = "code  status  rev  week  parties"


def print_trades(trades: list[dict]) -> None:
    """Print the trade rows under a header, or say plainly that there are none.

    Empty output is ambiguous -- a command that printed nothing may have failed
    -- and an unlabelled row of five fields is a puzzle. Both are read in
    Discord through `guillotine-ops`, so both get words.
    """
    if not trades:
        print("no trades recorded")
        return
    print(LIST_HEADER)
    for trade in trades:
        parties = ", ".join(
            p.get("display_name", "?") for p in (trade["terms"] or {}).get("parties", [])
        )
        week = trade["effective_week"] if trade["effective_week"] is not None else "-"
        print(f"{trade['trade_code']}  {trade['status']}  {trade['revision']}  {week}  {parties}")


def cmd_list(args: argparse.Namespace) -> int:
    deps = build_deps()
    print_trades(TradeRepository(deps.conn).list_recent(args.limit))
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
        TradeRepository(conn, code_prefix_for(deps.settings.delivery_mode)),
        RunRepository(conn),
        sleeper_client=SleeperClient(httpx.Client()),
    )
    status = registrar.handle(msg, retry=True)
    print(f"retry: {status}")
    # A failed retry has to be visible to whatever re-ran it, not just printed.
    return 1 if status == "failed" else 0


def load_replay_rows(path: str | Path) -> list[tuple[str, str, list[str]]]:
    """Read `(week, alert text, parties)` out of a contracts spreadsheet.

    The sheet is `Date, Week, Terms, Parties...`, one trade per row, with each
    column after `Terms` holding one party name. Rows with an empty `Terms` cell
    are spacers and are skipped. The `Terms` cell is the announcement without its
    siren, so the siren is put back: detection keys on it, and replaying text the
    trigger would never have seen would measure the wrong thing.

    Two shapes read as empty and are therefore skipped: a `Terms` cell merged
    across several rows (only the top-left cell of a merge carries the value, so
    the rows under it come back `None`), and a formula cell with no cached value
    (the workbook is opened `data_only=True`, which returns the last value Excel
    saved and `None` when it never calculated one). Neither is worth guessing at
    -- a replay that invented text would measure the wrong history.
    """
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook[workbook.sheetnames[0]]
        rows = []
        for row in list(sheet.iter_rows(values_only=True))[1:]:
            terms = _cell(row, TERMS_COLUMN)
            if not terms:
                continue
            parties = [p for p in (_cell(row, i) for i in range(TERMS_COLUMN + 1, len(row))) if p]
            rows.append((_cell(row, WEEK_COLUMN), f"{ALERT} {terms}", parties))
        return rows
    finally:
        workbook.close()


def _cell(row: tuple, index: int) -> str:
    if index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).strip()


def replay_rows(
    rows: Iterable[tuple[str, str, list[str]]], run_row: Callable[[int, str], str]
) -> int:
    """Print one outcome line per row and a closing summary; return an exit code.

    Detection lives here rather than in `run_row` so both modes agree on what the
    listener would even have looked at: a row the trigger would have ignored costs
    no model call and is reported as `not-a-candidate`. `run_row` is given the
    workbook row index as well as the text, so the two modes number rows the same
    way and write mode can date each replayed message from its place in the sheet.
    """
    counts = dict.fromkeys(SUMMARY_FIXED + SUMMARY_EXTRA, 0)
    total = 0
    for index, (_week, text, _parties) in enumerate(rows, start=1):
        total = index
        outcome = run_row(index, text) if is_trade_candidate(text) else "not-a-candidate"
        print(f"row {index}: {outcome}")
        # `clarification: <reason>` counts as a clarification.
        head = outcome.split(":", 1)[0].strip()
        if head in counts:
            counts[head] += 1
    parts = [f"{name} {counts[name]}" for name in SUMMARY_FIXED]
    parts += [f"{name} {counts[name]}" for name in SUMMARY_EXTRA if counts[name]]
    print(f"replay: {total} rows, " + ", ".join(parts))
    return 0


def _outcome(status: str) -> str:
    """Spell a registrar status the way the replay output spells it.

    `not_a_trade` is the one status written with underscores; every replay line
    and every summary counter is hyphenated, so it is hyphenated here rather than
    renamed at the source -- the registrar's return value is part of its contract.
    """
    return "not-a-trade" if status == "not_a_trade" else status


class _SilentNotifier:
    """Stands in for Hermes so a replay never pages Discord.

    A replay of a past season fails on rows nobody is going to fix -- a member
    who left the league, a player who retired -- and each failure would
    otherwise post an alert. The per-row `row N: failed` line is the report.
    """

    def ops(self, text: str) -> bool:
        return True

    def alerts(self, text: str) -> bool:
        return True


class _SilentDelivery:
    """Stands in for the delivery service so a replay can never post to a chat.

    Write mode exists to fill the tables from history, not to re-announce a season
    of trades years late. Refusing to send is enforced here rather than by trusting
    `DELIVERY_MODE`, so a mis-set mode cannot turn a replay into a broadcast.
    """

    def deliver(self, run_id, agent: str, content: str) -> None:
        return None


def cmd_replay(args: argparse.Namespace) -> int:
    """Replay a season of announcements from the contracts spreadsheet.

    `--dry-run` resolves only. Without it the registrar runs for real -- writes
    included, sends never -- and only outside production: replaying history into
    the live league would be indistinguishable from a flood of new trades.
    """
    # The refusal is read off the settings alone, before `build_deps` opens a
    # database connection: a replay pointed at production must not so much as
    # connect to it.
    if not args.dry_run and load_settings().delivery_mode is DeliveryMode.PRODUCTION:
        print("replay refuses to write in production; unset DELIVERY_MODE or use --dry-run")
        return 2
    rows = load_replay_rows(args.xlsx)
    if args.limit is not None:
        rows = rows[: args.limit]
    deps = build_deps()
    # Before the workbook is walked, so a missing key costs no HTTP call at all.
    ai = build_ai(deps)
    conn = deps.conn
    # Every accept needs the season row, and finding that out row by row would
    # burn a model call per failure before reporting the one thing that is wrong.
    if not args.dry_run and not SeasonRepository(conn).exists(REPLAY_SEASON):
        print(f"no public.seasons row for {REPLAY_SEASON}; insert it first")
        return 2
    if args.dry_run:
        members = MemberAliasRepository(conn).all_members()
        players = PlayerRepository(conn).all_active()

        def run_row(_index: int, text: str) -> str:
            result = dry_run_pipeline(
                ai, text, REPLAY_SEASON, members, players, RosterIndex.empty()
            )
            if result is NOT_A_TRADE:
                return "not-a-trade"
            if isinstance(result, Unresolved):
                return f"clarification: {result.reason}"
            return "created"

        return replay_rows(rows, run_row)

    registrar = TradeRegistrar(
        deps.settings,
        conn,
        ai,
        _SilentDelivery(),
        _SilentNotifier(),
        MemberAliasRepository(conn),
        PlayerRepository(conn),
        TradeRepository(conn, code_prefix_for(deps.settings.delivery_mode)),
        RunRepository(conn),
        season=REPLAY_SEASON,
        clock=lambda: REPLAY_CLOCK,
    )

    def run_row(index: int, text: str) -> str:
        # One day per workbook row, so replayed messages carry the sheet's order.
        # Dating from the row index rather than a counter of the rows that got
        # this far keeps a row's date the same whether or not the rows above it
        # were candidates.
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        msg = InboundMessage(
            guid=f"replay:{digest}",
            chat_guid=deps.settings.test_chat_guid or "replay",
            sender_address=None,
            text=text,
            is_from_me=False,
            is_group=True,
            sent_at=REPLAY_START + timedelta(days=index - 1),
        )
        return _outcome(registrar.handle(msg))

    return replay_rows(rows, run_row)
