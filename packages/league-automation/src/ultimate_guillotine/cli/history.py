"""`ug history` subcommands: load-catalog.

An operator command Ben runs on the Mac mini, and it prints counts and nothing else.
The input names real people -- the classification file's parties, and the chat the
analyst read to write it -- so a loader that echoed a row back would put a league
member's name in a terminal scrollback and, worse, teach the next command that doing
so is normal.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from ultimate_guillotine.cli.deps import build_deps
from ultimate_guillotine.data.repositories import MemberAliasRepository
from ultimate_guillotine.history.catalog import PlayerIndex, build_label_index, read_record
from ultimate_guillotine.history.repository import HistoryRepository, HistoryRowRejected
from ultimate_guillotine.sleeper.players import PlayerRepository


def register(subparsers) -> None:
    parser = subparsers.add_parser("history", help="league history loaders")
    history_sub = parser.add_subparsers(dest="command", required=True)

    catalog = history_sub.add_parser("load-catalog", help="load the private trade classification")
    catalog.add_argument("path")
    catalog.set_defaults(handler=cmd_load_catalog)


def cmd_load_catalog(args: argparse.Namespace) -> int:
    """Upsert every classification record into public.trade_catalog.

    The whole file loads in one transaction: a run that dies halfway through leaves the
    table as it was rather than half a catalog the pages would render as the whole thing.
    A single row the jsonb validators refuse is the exception -- the repository writes
    each row in its own savepoint -- and it is reported on stderr by its catalog id and
    skipped, because one malformed record should not cost the other hundred and sixty.

    Unresolved parties and dropped conditions are counted rather than guessed: Ben adds
    an alias with `ug members aliases load` and reruns, and the first count drops. Both
    counts describe the file as read; `rows` describes what actually landed. Exit 1 only
    when nothing loaded at all, which means the file is for another league, the members
    table has not been synced, or every row was refused.
    """
    deps = build_deps()
    document = json.loads(Path(args.path).read_text(encoding="utf-8"))
    records = document.get("trades", document if isinstance(document, list) else [])
    loaded_at = datetime.now(UTC)

    season_ids: dict[int, int | None] = {}
    loaded = unresolved = unmapped = 0
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
            reading = read_record(record, index, players, season_ids[season], loaded_at)
            unresolved += reading.row.unresolved_parties
            unmapped += reading.unmapped_conditions
            try:
                repo.upsert_catalog(reading.row)
            except HistoryRowRejected as exc:
                # The message names the row's natural key and the constraint, never the
                # payload that tripped it -- which is the whole reason it exists.
                print(f"rejected: {exc}", file=sys.stderr)
                continue
            loaded += 1

    print(f"catalog: {loaded} rows, {unresolved} unresolved parties, {unmapped} unmapped conditions")
    return 1 if loaded == 0 else 0
