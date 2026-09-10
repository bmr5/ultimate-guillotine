"""The executed transaction log, from Sleeper into ``public.transactions`` and
``public.transaction_moves``.

Spec: docs/superpowers/specs/2026-09-10-player-card-design.md. The feed is
``/league/{id}/transactions/{week}``, one record per transaction of that leg:
``type`` (trade, waiver, free_agent, commissioner), ``status``, ``created`` and
``status_updated`` as millisecond epochs, ``leg``, ``roster_ids``, ``adds`` and
``drops`` as ``{player_id: roster_id}`` maps (``adds`` is the receiving roster,
``drops`` the sending one), ``waiver_budget`` as ``{amount, sender, receiver}``
roster transfers, and ``settings.waiver_bid`` on a claim.

Only completed records are kept: a failed waiver bid says nothing about a
player's journey, and 2025 had 1,269 of them. An unknown ``type`` and a roster
with no team row are counted and skipped rather than failing the run -- one new
string from Sleeper must not stall the log -- on the players sync's reasoning.

Shaped like ``scores.py``: fetch every week first, parse with a pure loader,
upsert on ``sleeper_transaction_id`` inside the transaction ``run_scheduled``
already holds. Nothing is deleted; a rerun rewrites the same rows.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.teams import teams_by_roster_id
from ultimate_guillotine.sleeper.values import as_int, from_millis

#: The four kinds Sleeper's log carries and the column's check constraint admits.
KINDS = frozenset({"trade", "waiver", "free_agent", "commissioner"})


@dataclass(frozen=True)
class FaabMove:
    amount: int
    from_team_id: int
    to_team_id: int


@dataclass(frozen=True)
class Move:
    """One player on one side of a transaction: added to a team, or dropped by one."""

    sleeper_player_id: str
    team_id: int
    action: str


@dataclass(frozen=True)
class Transaction:
    """One completed transaction, mapped off roster ids onto team ids."""

    sleeper_transaction_id: str
    kind: str
    #: Sleeper's ``leg``: the week the transaction was processed in, never the clock.
    week: int
    occurred_at: datetime
    team_ids: list[int]
    faab_moves: list[FaabMove]
    waiver_bid: int | None
    raw: dict[str, Any]
    moves: list[Move]


@dataclass(frozen=True)
class TransactionLoad:
    """The transactions a payload yielded, and what could not be read off it."""

    transactions: list[Transaction]
    unknown_kinds: Counter[str] = field(default_factory=Counter)
    unmatched_rosters: int = 0
    malformed: int = 0


@dataclass(frozen=True)
class TransactionReport:
    """What one ``ug sleeper transactions`` run wrote. Counts only, never a name."""

    transactions: int
    moves: int
    weeks: list[int]
    unknown_kinds: Counter[str] = field(default_factory=Counter)
    unmatched_rosters: int = 0
    malformed: int = 0


def _team_for(roster: object, team_by_roster_id: dict[int, int]) -> int | None:
    roster_id = as_int(roster)
    return None if roster_id is None else team_by_roster_id.get(roster_id)


def _team_map(value: object, team_by_roster_id: dict[int, int]) -> dict[str, int] | None:
    """An ``adds``/``drops`` map as player id -> team id; None when a roster is unknown."""
    if not isinstance(value, dict):
        return {}
    mapped: dict[str, int] = {}
    for player_id, roster in value.items():
        team_id = _team_for(roster, team_by_roster_id)
        if team_id is None:
            return None
        mapped[str(player_id)] = team_id
    return mapped


def _faab_moves(value: object, team_by_roster_id: dict[int, int]) -> list[FaabMove] | None:
    if not isinstance(value, list):
        return []
    moves: list[FaabMove] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        amount = as_int(entry.get("amount"))
        if amount is None:
            continue
        sender = _team_for(entry.get("sender"), team_by_roster_id)
        receiver = _team_for(entry.get("receiver"), team_by_roster_id)
        if sender is None or receiver is None:
            return None
        moves.append(FaabMove(amount, sender, receiver))
    return moves


def _team_ids(value: object, team_by_roster_id: dict[int, int]) -> list[int] | None:
    if not isinstance(value, list):
        return []
    team_ids: list[int] = []
    for roster in value:
        team_id = _team_for(roster, team_by_roster_id)
        if team_id is None:
            return None
        team_ids.append(team_id)
    return team_ids


def load_transactions(
    payload: list[dict[str, Any]], team_by_roster_id: dict[int, int]
) -> TransactionLoad:
    """Parse one week's log into rows, counting what was skipped and why."""
    transactions: list[Transaction] = []
    unknown: Counter[str] = Counter()
    unmatched = 0
    malformed = 0
    for record in payload:
        if not isinstance(record, dict):
            malformed += 1
            continue
        if record.get("status") != "complete":
            continue
        kind = record.get("type")
        if kind not in KINDS:
            unknown[str(kind)] += 1
            continue
        transaction_id = record.get("transaction_id")
        week = as_int(record.get("leg"))
        occurred_at = from_millis(record.get("status_updated")) or from_millis(
            record.get("created")
        )
        if (
            not isinstance(transaction_id, str)
            or not transaction_id
            or week is None
            or occurred_at is None
        ):
            malformed += 1
            continue
        team_ids = _team_ids(record.get("roster_ids"), team_by_roster_id)
        adds = _team_map(record.get("adds"), team_by_roster_id)
        drops = _team_map(record.get("drops"), team_by_roster_id)
        faab = _faab_moves(record.get("waiver_budget"), team_by_roster_id)
        if team_ids is None or adds is None or drops is None or faab is None:
            unmatched += 1
            continue
        settings = record.get("settings")
        bid = None
        if kind == "waiver" and isinstance(settings, dict):
            bid = as_int(settings.get("waiver_bid"))
        moves = [Move(pid, tid, "add") for pid, tid in adds.items()]
        moves += [Move(pid, tid, "drop") for pid, tid in drops.items()]
        transactions.append(
            Transaction(
                sleeper_transaction_id=transaction_id,
                kind=kind,
                week=week,
                occurred_at=occurred_at,
                team_ids=team_ids,
                faab_moves=faab,
                waiver_bid=bid,
                raw=dict(record),
                moves=moves,
            )
        )
    return TransactionLoad(transactions, unknown, unmatched, malformed)


class TransactionRepository:
    """Writes for the transaction log. Runs on the caller's connection and transaction."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def upsert_many(
        self, season_id: int, transactions: list[Transaction], now: datetime
    ) -> tuple[int, int]:
        """Write each transaction and its moves; returns ``(transactions, moves)`` written.

        The transaction row upserts on ``sleeper_transaction_id`` and returns its id,
        which the moves then key on. A move upserts on
        ``(transaction_id, sleeper_player_id, action)``. A move Sleeper later removes
        from a record would be left standing -- nothing here deletes -- which the raw
        column makes visible and which has never been observed.
        """
        moves_written = 0
        with self._conn.cursor() as cur:
            for tx in transactions:
                cur.execute(
                    """
                    insert into public.transactions
                      (season_id, sleeper_transaction_id, kind, week, occurred_at, team_ids,
                       faab_moves, waiver_bid, raw, synced_at)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (sleeper_transaction_id) do update set
                      kind = excluded.kind,
                      week = excluded.week,
                      occurred_at = excluded.occurred_at,
                      team_ids = excluded.team_ids,
                      faab_moves = excluded.faab_moves,
                      waiver_bid = excluded.waiver_bid,
                      raw = excluded.raw,
                      synced_at = excluded.synced_at
                    returning id
                    """,
                    (
                        season_id,
                        tx.sleeper_transaction_id,
                        tx.kind,
                        tx.week,
                        tx.occurred_at,
                        tx.team_ids,
                        Jsonb(
                            [
                                {
                                    "amount": m.amount,
                                    "from_team_id": m.from_team_id,
                                    "to_team_id": m.to_team_id,
                                }
                                for m in tx.faab_moves
                            ]
                        ),
                        tx.waiver_bid,
                        Jsonb(tx.raw),
                        now,
                    ),
                )
                transaction_id = cur.fetchone()[0]
                if tx.moves:
                    cur.executemany(
                        """
                        insert into public.transaction_moves
                          (transaction_id, season_id, sleeper_player_id, team_id, action)
                        values (%s, %s, %s, %s, %s)
                        on conflict (transaction_id, sleeper_player_id, action) do update set
                          team_id = excluded.team_id
                        """,
                        [
                            (transaction_id, season_id, m.sleeper_player_id, m.team_id, m.action)
                            for m in tx.moves
                        ],
                    )
                    moves_written += len(tx.moves)
        return len(transactions), moves_written


def sync_transactions(
    client: SleeperClient,
    conn: psycopg.Connection,
    league_id: str,
    season_id: int,
    weeks: Sequence[int],
    now: datetime,
) -> TransactionReport:
    """Fetch the given weeks' logs, then upsert every completed transaction and its moves.

    Every week is fetched before anything is written, so a failing week aborts the
    run with the last good rows untouched. An empty week is normal -- a quiet
    Tuesday -- and writes nothing; the one refusal is a season with no teams to map
    onto, which is ``ug sleeper sync`` not having run.
    """
    team_map = teams_by_roster_id(conn, season_id)
    if not team_map:
        raise ValueError("no teams for the season; run ug sleeper sync first")
    payloads: list[tuple[int, list[dict[str, Any]]]] = []
    for week in weeks:
        payload = client.get_transactions(league_id, week)
        if not isinstance(payload, list):
            raise TypeError(f"sleeper returned no transaction list for week {week}")
        payloads.append((week, payload))
    repo = TransactionRepository(conn)
    unknown: Counter[str] = Counter()
    unmatched = malformed = written = moves = 0
    for _week, payload in payloads:
        load = load_transactions(payload, team_map)
        unknown.update(load.unknown_kinds)
        unmatched += load.unmatched_rosters
        malformed += load.malformed
        wrote, moved = repo.upsert_many(season_id, load.transactions, now)
        written += wrote
        moves += moved
    return TransactionReport(
        transactions=written,
        moves=moves,
        weeks=list(weeks),
        unknown_kinds=unknown,
        unmatched_rosters=unmatched,
        malformed=malformed,
    )
