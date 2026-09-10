"""`ug history` subcommands: load-catalog and load-results.

An operator command Ben runs on the Mac mini, and it prints counts and nothing else.
The input names real people -- the classification file's parties, the chat the analyst
read to write it, and the records workbook's champion cells, which sit in the same file
as the dues ledger -- so a loader that echoed a row back would put a league member's
name in a terminal scrollback and, worse, teach the next command that doing so is
normal.
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
    CatalogRecordRefused,
    PlayerIndex,
    build_label_index,
    read_record,
)
from ultimate_guillotine.history.records import season_result_rows
from ultimate_guillotine.history.repository import HistoryRepository, HistoryRowRejected
from ultimate_guillotine.sleeper.players import PlayerRepository


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
    still state nothing. Opening the workbook in Excel, saving, and rerunning drives that
    count down. Without it, a load reports six clean seasons over a file full of holes.
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
