"""Writes for the two public history tables.

Both upsert on a natural key, so a rerun after Ben fixes an alias updates the row
in place rather than allocating a second one. `xmax = 0` is Postgres' own answer to
"did this INSERT ... ON CONFLICT insert or update", which beats a prior SELECT.

Each write runs inside its own savepoint so that a row the jsonb validators refuse
rolls back alone: the loader keeps its connection and can carry on with the next
row. The rejection is re-raised as `HistoryRowRejected`, which names the offending
row by its natural key and the constraint that refused it -- never the text that
tripped it, which is exactly the unvetted chat or workbook content the validators
exist to keep out of Postgres and out of the logs.
"""

import psycopg
from psycopg.types.json import Jsonb

from ultimate_guillotine.history.models import CatalogRow, SeasonResultRow


class HistoryRowRejected(RuntimeError):
    """A history row the database refused. Carries the natural key, not the payload."""


def _rejected(label: str, exc: psycopg.errors.IntegrityError) -> HistoryRowRejected:
    constraint = exc.diag.constraint_name or "an unnamed constraint"
    # `from None` at the raise site keeps psycopg's own message -- which quotes the
    # failing row in full -- out of the traceback.
    return HistoryRowRejected(f"{label} was refused by {constraint}")


class HistoryRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def season_id_for(self, year: int) -> int | None:
        """The public.seasons id for a year, or None for a season the league has no row for."""
        with self._conn.cursor() as cur:
            cur.execute("select id from public.seasons where year = %s", (year,))
            row = cur.fetchone()
        return row[0] if row else None

    def upsert_catalog(self, row: CatalogRow) -> str:
        try:
            with self._conn.transaction(), self._conn.cursor() as cur:
                cur.execute(
                    """
                    insert into public.trade_catalog (
                        catalog_id, season, season_id, week, occurred_on, trade_type, structure,
                        party_member_ids, party_count, assets, faab_total, confidence,
                        unresolved_parties, loaded_at
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (catalog_id) do update set
                        season = excluded.season,
                        season_id = excluded.season_id,
                        week = excluded.week,
                        occurred_on = excluded.occurred_on,
                        trade_type = excluded.trade_type,
                        structure = excluded.structure,
                        party_member_ids = excluded.party_member_ids,
                        party_count = excluded.party_count,
                        assets = excluded.assets,
                        faab_total = excluded.faab_total,
                        confidence = excluded.confidence,
                        unresolved_parties = excluded.unresolved_parties,
                        loaded_at = excluded.loaded_at
                    returning (xmax = 0)
                    """,
                    (
                        row.catalog_id, row.season, row.season_id, row.week, row.occurred_on,
                        row.trade_type, row.structure, row.party_member_ids, row.party_count,
                        Jsonb(row.assets), row.faab_total, row.confidence,
                        row.unresolved_parties, row.loaded_at,
                    ),
                )
                inserted = cur.fetchone()[0]
        except psycopg.errors.IntegrityError as exc:
            raise _rejected(f"trade_catalog row {row.catalog_id}", exc) from None
        return "inserted" if inserted else "updated"

    def upsert_season_result(self, row: SeasonResultRow) -> str:
        try:
            with self._conn.transaction(), self._conn.cursor() as cur:
                cur.execute(
                    """
                    insert into public.season_results (
                        season, season_id, champion_member_id, co_champion_member_id,
                        runner_up_member_id, third_member_id, team_count, eliminations, notes,
                        unresolved_names, loaded_at
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (season) do update set
                        season_id = excluded.season_id,
                        champion_member_id = excluded.champion_member_id,
                        co_champion_member_id = excluded.co_champion_member_id,
                        runner_up_member_id = excluded.runner_up_member_id,
                        third_member_id = excluded.third_member_id,
                        team_count = excluded.team_count,
                        eliminations = excluded.eliminations,
                        -- A note Ben typed on an earlier run survives a run that passes none.
                        notes = coalesce(excluded.notes, public.season_results.notes),
                        unresolved_names = excluded.unresolved_names,
                        loaded_at = excluded.loaded_at
                    returning (xmax = 0)
                    """,
                    (
                        row.season, row.season_id, row.champion_member_id,
                        row.co_champion_member_id, row.runner_up_member_id, row.third_member_id,
                        row.team_count, Jsonb(row.eliminations), row.notes,
                        row.unresolved_names, row.loaded_at,
                    ),
                )
                inserted = cur.fetchone()[0]
        except psycopg.errors.IntegrityError as exc:
            raise _rejected(f"season_results row for season {row.season}", exc) from None
        return "inserted" if inserted else "updated"
