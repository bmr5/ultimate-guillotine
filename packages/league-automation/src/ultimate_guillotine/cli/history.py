"""`ug history` subcommands: load-catalog, load-results and set-result.

An operator command Ben runs on the Mac mini, and it prints counts and nothing else.
The input names real people -- the classification file's parties, the chat the analyst
read to write it, the records workbook's champion cells, which sit in the same file as
the dues ledger, and the usernames Ben types into `set-result` -- so a command that
echoed one back would put a league member's name in a terminal scrollback and, worse,
teach the next command that doing so is normal.
"""

import argparse
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from ultimate_guillotine.cli.deps import build_deps
from ultimate_guillotine.data.repositories import MemberAliasRepository
from ultimate_guillotine.history.catalog import (
    AMBIGUOUS,
    CatalogRecordRefused,
    PlayerIndex,
    build_label_index,
    read_record,
)
from ultimate_guillotine.history.models import SeasonResultRow
from ultimate_guillotine.history.records import season_result_rows
from ultimate_guillotine.history.repository import HistoryRepository, HistoryRowRejected
from ultimate_guillotine.sleeper.players import PlayerRepository
from ultimate_guillotine.trades.names import normalize_name

#: What `set-result` says when a name resolves to nobody, or to two people. Fixed text:
#: the thing that failed to resolve is a league member's name, and a message that read it
#: back to say so would put it in the scrollback this whole module keeps clean. Which of
#: the four flags it was is left out for the same reason -- Ben typed the command a second
#: ago and can see it; the terminal keeps it forever.
UNRESOLVED_NAME = (
    "a name did not resolve to exactly one league member; "
    "add an alias with `ug members aliases load` and rerun"
)

#: The four placings `set-result` takes, in the order they are resolved, mapped onto the
#: `SeasonResultRow` columns they fill.
PLACINGS = (
    ("champion", "champion_member_id"),
    ("co_champion", "co_champion_member_id"),
    ("runner_up", "runner_up_member_id"),
    ("third", "third_member_id"),
)


def register(subparsers) -> None:
    parser = subparsers.add_parser("history", help="league history loaders")
    history_sub = parser.add_subparsers(dest="command", required=True)

    catalog = history_sub.add_parser("load-catalog", help="load the private trade classification")
    catalog.add_argument("path")
    catalog.set_defaults(handler=cmd_load_catalog)

    results = history_sub.add_parser(
        "load-results", help="load the records workbook's public sheets"
    )
    results.add_argument("path")
    results.add_argument(
        "--notes",
        action="append",
        default=[],
        metavar="SEASON=TEXT",
        help="a caption for one season, e.g. 2022=co-champions; repeatable",
    )
    results.set_defaults(handler=cmd_load_results)

    hand = history_sub.add_parser("set-result", help="record one season's placings by hand")
    hand.add_argument("--season", type=int, required=True, metavar="YEAR")
    hand.add_argument("--champion", required=True, metavar="USERNAME")
    hand.add_argument("--co-champion", dest="co_champion", metavar="USERNAME")
    hand.add_argument("--runner-up", dest="runner_up", metavar="USERNAME")
    hand.add_argument("--third", metavar="USERNAME")
    hand.add_argument("--team-count", dest="team_count", type=int, metavar="N")
    hand.add_argument("--notes", metavar="TEXT", help="a caption for the season")
    hand.set_defaults(handler=cmd_set_result)


def cmd_load_catalog(args: argparse.Namespace) -> int:
    """Upsert every classification record into public.trade_catalog.

    The whole file loads in one transaction: a run that dies halfway through leaves the
    table as it was rather than half a catalog the pages would render as the whole thing.
    A single refused row is the exception -- whether the reader refused it or the jsonb
    validators did, the repository writes each row in its own savepoint -- and it is
    reported on stderr by its catalog id and skipped, because one malformed record should
    not cost the other hundred and sixty.

    Unresolved parties and dropped conditions are counted rather than guessed: Ben adds
    an alias with `ug members aliases load` and reruns, and the first count drops. Both
    counts describe the file as read, minus any record the reader refused outright.
    `rows` is what landed and `updated` is how much of that was already there, so a
    rerun after an alias fix reads as "165 rows, 165 updated" rather than as a load that
    might have doubled the table. Exit 1 only when nothing loaded at all, which means the
    file is for another league, the members table has not been synced, or every row was
    refused.
    """
    deps = build_deps()
    document = json.loads(Path(args.path).read_text(encoding="utf-8"))
    records = document.get("trades", document if isinstance(document, list) else [])
    loaded_at = datetime.now(UTC)

    season_ids: dict[int, int | None] = {}
    loaded = updated = unresolved = unmapped = 0
    # The reads belong inside the transaction too. A query taken before it starts the
    # connection's transaction implicitly, `conn.transaction()` then opens a savepoint
    # inside that one rather than a transaction of its own, and the whole load is rolled
    # back when the connection closes -- after reporting every row as loaded.
    with deps.conn.transaction():
        repo = HistoryRepository(deps.conn)
        index = build_label_index(MemberAliasRepository(deps.conn).all_members())
        players = PlayerIndex(PlayerRepository(deps.conn).all_active())
        for record in records:
            season = int(record["season"])
            if season not in season_ids:
                season_ids[season] = repo.season_id_for(season)
            try:
                reading = read_record(record, index, players, season_ids[season], loaded_at)
                unresolved += reading.row.unresolved_parties
                unmapped += reading.unmapped_conditions
                outcome = repo.upsert_catalog(reading.row)
            except (CatalogRecordRefused, HistoryRowRejected) as exc:
                # Both messages name the row's natural key and what refused it, never the
                # payload that tripped it -- which is the whole reason they exist.
                print(f"rejected: {exc}", file=sys.stderr)
                continue
            loaded += 1
            updated += outcome == "updated"

    print(
        f"catalog: {loaded} rows, {updated} updated, "
        f"{unresolved} unresolved parties, {unmapped} unmapped conditions"
    )
    return 1 if loaded == 0 else 0


def _parse_notes(pairs: list[str]) -> dict[int, str]:
    """`--notes 2022=co-champions` into `{2022: "co-champions"}`.

    The usage message is fixed text: a malformed pair is Ben's typo, and echoing it back
    would be the one place this command printed something it was handed.
    """
    notes: dict[int, str] = {}
    for pair in pairs:
        season, _, text = pair.partition("=")
        if not text.strip() or not season.strip().isdigit():
            raise SystemExit("--notes takes SEASON=TEXT")
        notes[int(season.strip())] = text.strip()
    return notes


def cmd_load_results(args: argparse.Namespace) -> int:
    """Upsert one public.season_results row per season in the workbook's Winners sheet.

    The reader opens three sheets of the workbook and no others -- the file is also the
    commissioner's dues ledger -- and it resolves the champion cells to member ids here,
    inside the transaction, against the members table and the private aliases. A name
    nobody answers to is counted, never stored and never printed: Ben adds an alias with
    `ug members aliases load` and reruns, and the count drops.

    The whole workbook loads in one transaction, for the same reason the catalog does: a
    run that dies halfway leaves the table as it was rather than half a history the pages
    would render as the whole thing. A row the jsonb validator refuses is reported on
    stderr by its season and skipped. Exit 1 only when nothing landed at all, which means
    the Winners sheet is empty or every row was refused.

    `weeks with no count` is the last number on the line because it is the one Ben can
    act on without touching the loader: the workbook's grids are mostly formulas and the
    file has never been saved with its results cached, so a week can exist as a row and
    state one of its two counts, or neither. Every such week row counts once here, entry
    or no entry. Opening the workbook in Excel, saving, and rerunning drives that count
    down. Without it, a load reports six clean seasons over a file full of holes.
    """
    deps = build_deps()
    notes = _parse_notes(args.notes)
    loaded_at = datetime.now(UTC)

    loaded = updated = unresolved = silent_weeks = 0
    # The reads belong inside the transaction too -- see `cmd_load_catalog` for why a
    # query taken first turns the whole load into a savepoint that rolls back at exit.
    with deps.conn.transaction():
        repo = HistoryRepository(deps.conn)
        index = build_label_index(MemberAliasRepository(deps.conn).all_members())
        rows, unresolved, silent_weeks = season_result_rows(
            Path(args.path), index, notes, loaded_at
        )
        for row in rows:
            stored = replace(row, season_id=repo.season_id_for(row.season))
            try:
                outcome = repo.upsert_season_result(stored)
            except HistoryRowRejected as exc:
                # The message names the season and the constraint, never the row.
                print(f"rejected: {exc}", file=sys.stderr)
                continue
            loaded += 1
            updated += outcome == "updated"

    print(
        f"results: {loaded} seasons, {updated} updated, "
        f"{unresolved} unresolved names, {silent_weeks} weeks with no count"
    )
    return 1 if loaded == 0 else 0


def cmd_set_result(args: argparse.Namespace) -> int:
    """Write one public.season_results row from the command line.

    The records workbook is not the whole record. Its `Winners` sheet is a year behind
    the league -- 2025 has no row on it, and the only sheet that knows about 2025 is the
    dues roster the reader will not open -- so `load-results` publishes the six seasons
    the sheet carries and silently omits the one Ben won. This is the door for a season
    the workbook does not cover, and it takes what the workbook would have said: who
    placed, how many teams started, and a caption.

    Names resolve exactly the way both loaders resolve them -- `build_label_index` over
    the members table and the private aliases -- so a nickname, a Sleeper display name or
    an alias all work, and the id is what is stored. But where a loader reading a file
    counts an unresolved name and carries on, this one stops: a loader is reading six
    seasons and one hole in it is a number Ben can chase, while this command is one
    season with one champion in it, and a row published with a null champion because a
    username was misspelt is worse than no row at all. Nothing is written on that path.

    `eliminations` is read back and handed over unchanged: this command is told placings
    and has no week grid, and a rerun to add a runner-up must not blank the weeks a
    `load-results` run put there. `notes` is coalesced by the upsert for the same reason.
    Everything else on the row is the flags as typed -- omitting `--team-count` on a
    rerun clears the count, because the command's arguments are the season's placings and
    a half-remembered one is not a thing to preserve.
    """
    deps = build_deps()
    loaded_at = datetime.now(UTC)

    # The reads belong inside the transaction too -- see `cmd_load_catalog` for why a
    # query taken first turns the write into a savepoint that rolls back at exit.
    with deps.conn.transaction():
        repo = HistoryRepository(deps.conn)
        index = build_label_index(MemberAliasRepository(deps.conn).all_members())
        placings: dict[str, int | None] = {}
        for flag, column in PLACINGS:
            name = getattr(args, flag)
            if name is None:
                placings[column] = None
                continue
            # `AMBIGUOUS` is None as well, so a label two members answer to takes the
            # same exit as a label nobody does. Both mean the same thing here: the
            # command cannot say whose season this was.
            member_id = index.get(normalize_name(name), AMBIGUOUS)
            if member_id is None:
                print(UNRESOLVED_NAME, file=sys.stderr)
                return 1
            placings[column] = member_id
        row = SeasonResultRow(
            season=args.season,
            season_id=repo.season_id_for(args.season),
            team_count=args.team_count,
            eliminations=repo.eliminations_for(args.season),
            notes=args.notes,
            unresolved_names=0,
            loaded_at=loaded_at,
            **placings,
        )
        outcome = repo.upsert_season_result(row)

    print(f"result: season {args.season} {'created' if outcome == 'inserted' else 'updated'}")
    return 0
