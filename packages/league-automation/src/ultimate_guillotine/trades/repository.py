"""Persistence for accepted trades, their revisions, and rescissions.

Like ``data.repositories``, ``TradeRepository`` takes an already-open
``psycopg.Connection`` and issues parameterized SQL only. ``accept`` is the one
method that opens its own ``conn.transaction()``: allocating a trade code from a
count and inserting the trade, its revision, and its league event have to happen
together or not at all.

Idempotency has two layers. The semantic fingerprint of a proposal is unique
across ``trade_revisions``, so a reposted message resolves to the same terms and
comes back as a ``duplicate``. The context key (season, parties, players) is
carried on ``trades``, so an amended version of an already-accepted trade lands
as a new revision of that trade rather than as a second trade -- but only while
that trade is still recent (``REVISE_WINDOW_HOURS``); the same two people
trading the same player again next week is a new deal.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import psycopg
from psycopg.types.json import Jsonb

from ultimate_guillotine.trades.fingerprint import trade_context_key, trade_fingerprint
from ultimate_guillotine.trades.models import TradeProposal

AcceptStatus = Literal["created", "duplicate", "revised"]

#: How long an accepted trade stays open to revision by context. A correction
#: arrives within minutes or hours; the same two people trading the same player
#: again days later is a new deal, not an amendment of the old one.
REVISE_WINDOW_HOURS = 72

_TRADE_SELECT = """
    select t.id, t.trade_code, t.status, r.revision, r.terms, r.effective_week
    from public.trades t
    join public.trade_revisions r on r.id = t.current_revision_id
"""


@dataclass(frozen=True)
class TradeAcceptance:
    """The outcome of ``TradeRepository.accept``.

    ``previous_terms`` is the superseded terms document, set only when the
    status is ``revised``.
    """

    status: AcceptStatus
    trade_id: int
    trade_code: str
    revision: int
    previous_terms: dict | None


def _trade_row(row: tuple) -> dict:
    return {
        "trade_id": row[0],
        "trade_code": row[1],
        "status": row[2],
        "revision": row[3],
        "terms": row[4],
        "effective_week": row[5],
    }


class TradeRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def accept(self, proposal: TradeProposal) -> TradeAcceptance:
        """Record ``proposal``, reporting whether it created, duplicated, or
        revised a trade.

        Raises ``LookupError`` when the proposal's season has no row.
        """
        fingerprint = trade_fingerprint(proposal)
        context = trade_context_key(proposal)
        terms = proposal.model_dump(mode="json")
        try:
            with self._conn.transaction():
                return self._accept(proposal, fingerprint, context, terms)
        except psycopg.errors.UniqueViolation:
            # A concurrent writer recorded this fingerprint between our lookup
            # and our insert. The failed transaction is rolled back by now, so
            # re-read it in a fresh one and report the duplicate it created.
            with self._conn.transaction():
                duplicate = self._duplicate(fingerprint)
            if duplicate is None:
                raise
            return duplicate

    def rescind(self, trade_code: str, source_guid: str, occurred_at: datetime) -> bool:
        """Mark a trade rescinded and record the event.

        Returns ``False`` when no trade carries ``trade_code``. Re-rescinding
        from the same source message leaves the event log unchanged.

        The rescinded trade's revisions give up their semantic fingerprints, so
        the partial unique index no longer blocks the identical trade being
        announced again: a re-announcement becomes a new trade with a new code
        rather than a duplicate of the dead one.
        """
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(
                """
                update public.trades set status = 'rescinded'
                where trade_code = %s
                returning id, season_id
                """,
                (trade_code,),
            )
            row = cur.fetchone()
            if row is None:
                return False
            trade_id, season_id = row
            cur.execute(
                """
                update public.trade_revisions set semantic_fingerprint = null
                where trade_id = %s
                """,
                (trade_id,),
            )
            cur.execute(
                """
                insert into public.league_events
                    (season_id, week, event_type, occurred_at, payload, idempotency_key)
                values (%s, null, 'trade_rescinded', %s, %s, %s)
                on conflict (idempotency_key) do nothing
                """,
                (
                    season_id,
                    occurred_at,
                    Jsonb({"trade_code": trade_code, "source_message_guid": source_guid}),
                    f"rescind:{trade_code}:{source_guid}",
                ),
            )
            return True

    def find_by_code(self, code: str) -> dict | None:
        """Return the trade and its current terms, or ``None`` if unknown."""
        with self._conn.cursor() as cur:
            cur.execute(f"{_TRADE_SELECT} where t.trade_code = %s", (code,))
            row = cur.fetchone()
            return _trade_row(row) if row else None

    def find_by_id(self, trade_id: int) -> dict | None:
        """Return the trade with this id and its current terms, or ``None``.

        ``find_by_context`` answers with an id; a rescission that named no code
        needs the code itself to rescind and to say which trade it killed.
        """
        with self._conn.cursor() as cur:
            cur.execute(f"{_TRADE_SELECT} where t.id = %s", (trade_id,))
            row = cur.fetchone()
            return _trade_row(row) if row else None

    def find_by_context(
        self, context_key: str, *, within_hours: int = REVISE_WINDOW_HOURS
    ) -> int | None:
        """Return the id of the recently accepted trade with this context key, if any.

        Only a trade whose latest revision landed inside ``within_hours``
        counts: an uncoded rescission means the deal people are still talking
        about, not one from last month with the same players.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select t.id from public.trades t
                join public.trade_revisions r on r.id = t.current_revision_id
                where t.context_key = %s and t.status = 'accepted'
                  and r.created_at > now() - make_interval(hours => %s)
                order by t.id desc
                limit 1
                """,
                (context_key, within_hours),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def list_recent(self, limit: int = 10) -> list[dict]:
        """Return the newest trades, most recent first, in ``find_by_code`` shape."""
        with self._conn.cursor() as cur:
            cur.execute(f"{_TRADE_SELECT} order by t.id desc limit %s", (limit,))
            return [_trade_row(row) for row in cur.fetchall()]

    # -- internals ------------------------------------------------------

    def _accept(
        self,
        proposal: TradeProposal,
        fingerprint: str,
        context: str,
        terms: dict[str, Any],
    ) -> TradeAcceptance:
        with self._conn.cursor() as cur:
            cur.execute("select id from public.seasons where year = %s", (proposal.season,))
            row = cur.fetchone()
            if row is None:
                raise LookupError(f"No season row for {proposal.season}")
            season_id = row[0]

            # Trade codes are allocated from a count, so two accepts in the same
            # season must not overlap. The lock is held to the end of the
            # transaction and serializes every accept in this season.
            cur.execute("select pg_advisory_xact_lock(%s)", (season_id,))

            duplicate = self._duplicate(fingerprint, cur)
            if duplicate is not None:
                return duplicate

            # Only a recently revised trade is still open to amendment; an older
            # one with the same context falls through and gets a code of its own.
            cur.execute(
                """
                select t.id, t.trade_code, t.current_revision_id from public.trades t
                join public.trade_revisions r on r.id = t.current_revision_id
                where t.context_key = %s and t.status = 'accepted' and t.season_id = %s
                  and r.created_at > now() - make_interval(hours => %s)
                order by t.id desc
                limit 1
                """,
                (context, season_id, REVISE_WINDOW_HOURS),
            )
            open_trade = cur.fetchone()
            if open_trade is not None:
                trade_id, trade_code, current_revision_id = open_trade
                cur.execute(
                    "select terms from public.trade_revisions where id = %s",
                    (current_revision_id,),
                )
                current = cur.fetchone()
                if current is None:
                    raise RuntimeError(f"Trade {trade_code} has no current revision")
                previous_terms = current[0]
                revision = self._insert_revision(cur, trade_id, terms, fingerprint, proposal)
                return TradeAcceptance("revised", trade_id, trade_code, revision, previous_terms)

            cur.execute("select count(*) from public.trades where season_id = %s", (season_id,))
            sequence = cur.fetchone()[0] + 1
            trade_code = f"T-{proposal.season}-{sequence:03d}"
            cur.execute(
                """
                insert into public.trades (season_id, trade_code, context_key)
                values (%s, %s, %s)
                returning id
                """,
                (season_id, trade_code, context),
            )
            trade_id = cur.fetchone()[0]
            revision = self._insert_revision(cur, trade_id, terms, fingerprint, proposal)
            # The trade code is in the key as well as the fingerprint: a rescinded
            # trade re-announced with identical terms repeats the fingerprint, and
            # keying on that alone would let ``do nothing`` swallow the new trade's
            # event. The code is unique per trade and stable across replays.
            cur.execute(
                """
                insert into public.league_events
                    (season_id, week, event_type, occurred_at, payload, idempotency_key)
                values (%s, %s, 'trade', now(), %s, %s)
                on conflict (idempotency_key) do nothing
                """,
                (
                    season_id,
                    proposal.effective_week,
                    Jsonb({"trade_code": trade_code, "revision": revision}),
                    f"trade:{trade_code}:{fingerprint}",
                ),
            )
            return TradeAcceptance("created", trade_id, trade_code, revision, None)

    def _insert_revision(
        self,
        cur: psycopg.Cursor,
        trade_id: int,
        terms: dict[str, Any],
        fingerprint: str,
        proposal: TradeProposal,
    ) -> int:
        """Insert the next revision of a trade and point the trade at it."""
        cur.execute(
            "select coalesce(max(revision), 0) + 1 from public.trade_revisions where trade_id = %s",
            (trade_id,),
        )
        revision = cur.fetchone()[0]
        cur.execute(
            """
            insert into public.trade_revisions
                (trade_id, revision, terms, source_message_guid, effective_week,
                 semantic_fingerprint)
            values (%s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                trade_id,
                revision,
                Jsonb(terms),
                proposal.source_message_guid,
                proposal.effective_week,
                fingerprint,
            ),
        )
        revision_id = cur.fetchone()[0]
        cur.execute(
            "update public.trades set current_revision_id = %s where id = %s",
            (revision_id, trade_id),
        )
        return revision

    def _duplicate(
        self,
        fingerprint: str,
        cur: psycopg.Cursor | None = None,
    ) -> TradeAcceptance | None:
        """Return the acceptance for an already-recorded fingerprint, if any.

        Only live trades count: a rescinded trade's terms may be announced
        again, and that is a new trade rather than a duplicate.
        """
        if cur is None:
            with self._conn.cursor() as own_cur:
                return self._duplicate(fingerprint, own_cur)
        cur.execute(
            """
            select r.trade_id, t.trade_code, r.revision
            from public.trade_revisions r
            join public.trades t on t.id = r.trade_id and t.status = 'accepted'
            where r.semantic_fingerprint = %s
            """,
            (fingerprint,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return TradeAcceptance("duplicate", row[0], row[1], row[2], None)
