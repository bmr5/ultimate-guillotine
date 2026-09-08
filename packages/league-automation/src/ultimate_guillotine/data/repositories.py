"""Repositories over the ``private`` automation schema.

Every repository takes an already-open ``psycopg.Connection`` and issues
parameterized SQL only. Callers own the transaction (commit/rollback); no
repository method commits on the caller's behalf.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg

from ultimate_guillotine.config import DeliveryMode


def chat_guid_hash(chat_guid: str) -> str:
    """Return the SHA-256 hex digest of a BlueBubbles chat GUID."""
    return hashlib.sha256(chat_guid.encode()).hexdigest()


@dataclass(frozen=True)
class DeliveryTarget:
    id: int
    mode: str
    chat_guid: str
    participant_fingerprint: str | None
    label: str


@dataclass(frozen=True)
class OutboundRecord:
    id: int
    state: str
    reserved_at: datetime
    content_hash: str
    bluebubbles_guid: str | None


@dataclass(frozen=True)
class SourceMessage:
    source_guid: str
    chat_guid_hash: str
    sender_hash: str | None
    direction: str
    sent_at: datetime
    content_fingerprint: str
    excerpt: str | None
    trigger_name: str | None


@dataclass(frozen=True)
class ExpectedRun:
    job_name: str
    agent: str
    max_gap_minutes: int
    schedule: str


class RunRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def reserve(
        self,
        agent: str,
        trigger: str,
        idempotency_key: str,
        invoked_by: str | None = None,
    ) -> int | None:
        """Insert a new agent run, returning its id, or ``None`` if the
        idempotency key already exists."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into private.agent_runs (agent, trigger, idempotency_key, invoked_by)
                values (%s, %s, %s, %s)
                on conflict (idempotency_key) do nothing
                returning id
                """,
                (agent, trigger, idempotency_key, invoked_by),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def finish(
        self,
        run_id: int,
        status: str,
        output_hash: str | None = None,
        error: str | None = None,
    ) -> None:
        """Mark a run finished, recording its terminal status."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                update private.agent_runs
                set status = %s, output_hash = %s, error = %s, finished_at = now()
                where id = %s
                """,
                (status, output_hash, error, run_id),
            )

    def last_started(self, agent: str) -> datetime | None:
        """Return the most recent ``started_at`` for the given agent, if any."""
        with self._conn.cursor() as cur:
            cur.execute(
                "select max(started_at) from private.agent_runs where agent = %s",
                (agent,),
            )
            row = cur.fetchone()
            return row[0] if row else None


class TargetRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def get(self, mode: DeliveryMode) -> DeliveryTarget | None:
        """Look up the delivery target configured for ``mode``."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select id, mode, chat_guid, participant_fingerprint, label
                from private.delivery_targets
                where mode = %s
                """,
                (mode.value,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return DeliveryTarget(*row)

    def upsert(
        self,
        mode: DeliveryMode,
        chat_guid: str,
        participant_fingerprint: str | None,
        label: str,
    ) -> int:
        """Create or replace the delivery target for ``mode``, returning its id."""
        mode_value = mode.value
        guid_hash = chat_guid_hash(chat_guid)
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into private.delivery_targets
                    (mode, chat_guid, chat_guid_hash, participant_fingerprint, label)
                values (%s, %s, %s, %s, %s)
                on conflict (mode) do update
                    set chat_guid = excluded.chat_guid,
                        chat_guid_hash = excluded.chat_guid_hash,
                        participant_fingerprint = excluded.participant_fingerprint,
                        label = excluded.label
                returning id
                """,
                (mode_value, chat_guid, guid_hash, participant_fingerprint, label),
            )
            row = cur.fetchone()
            assert row is not None
            return row[0]


class OutboundRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def reserve(
        self,
        run_id: int | None,
        target_id: int,
        content: str,
        content_hash: str,
    ) -> int:
        """Reserve an outbound message slot, returning its id."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into private.outbound_messages
                    (run_id, delivery_target_id, content, content_hash)
                values (%s, %s, %s, %s)
                returning id
                """,
                (run_id, target_id, content, content_hash),
            )
            row = cur.fetchone()
            assert row is not None
            return row[0]

    def set_state(
        self,
        outbound_id: int,
        state: str,
        bluebubbles_guid: str | None = None,
        error: str | None = None,
    ) -> None:
        """Transition an outbound message's state.

        Sets ``sent_at = now()`` when the new state is ``sent`` or
        ``reconciled``, and writes ``error`` when one is given.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                update private.outbound_messages
                set state = %s,
                    bluebubbles_guid = coalesce(%s, bluebubbles_guid),
                    error = coalesce(%s, error),
                    sent_at = case when %s in ('sent', 'reconciled') then now() else sent_at end
                where id = %s
                """,
                (state, bluebubbles_guid, error, state, outbound_id),
            )

    def pending_sending(self, target_id: int, content_hash: str) -> OutboundRecord | None:
        """Return the most recent in-flight (``sending``) outbound message
        for this target/content, if any."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select id, state, reserved_at, content_hash, bluebubbles_guid
                from private.outbound_messages
                where delivery_target_id = %s and content_hash = %s and state = 'sending'
                order by reserved_at desc
                limit 1
                """,
                (target_id, content_hash),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return OutboundRecord(*row)


class ReceiptRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def record(self, event_id: str, outcome: str) -> bool:
        """Record a webhook receipt once. Returns ``False`` if already
        recorded."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into private.webhook_receipts (event_id, outcome)
                values (%s, %s)
                on conflict (event_id) do nothing
                returning id
                """,
                (event_id, outcome),
            )
            return cur.fetchone() is not None


class SourceMessageRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def upsert(self, msg: SourceMessage) -> bool:
        """Insert a source message once. Returns ``False`` if it already
        existed (by ``source_guid``)."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into private.source_messages
                    (source_guid, chat_guid_hash, sender_hash, direction, sent_at,
                     content_fingerprint, excerpt, trigger_name)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (source_guid) do nothing
                returning id
                """,
                (
                    msg.source_guid,
                    msg.chat_guid_hash,
                    msg.sender_hash,
                    msg.direction,
                    msg.sent_at,
                    msg.content_fingerprint,
                    msg.excerpt,
                    msg.trigger_name,
                ),
            )
            return cur.fetchone() is not None

    def latest_sent_at(self, chat_guid_hash: str) -> datetime | None:
        """Return the latest ``sent_at`` recorded for a given chat, if any."""
        with self._conn.cursor() as cur:
            cur.execute(
                "select max(sent_at) from private.source_messages where chat_guid_hash = %s",
                (chat_guid_hash,),
            )
            row = cur.fetchone()
            return row[0] if row else None


class HeartbeatRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def beat(self, component: str) -> None:
        """Record that ``component`` is alive right now."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into private.heartbeats (component, beat_at)
                values (%s, now())
                on conflict (component) do update set beat_at = now()
                """,
                (component,),
            )

    def stale(self, older_than: timedelta, now: datetime) -> list[str]:
        """Return the components whose last heartbeat is older than
        ``older_than`` relative to ``now``."""
        cutoff = now - older_than
        with self._conn.cursor() as cur:
            cur.execute(
                "select component from private.heartbeats where beat_at < %s",
                (cutoff,),
            )
            return [row[0] for row in cur.fetchall()]


class ExpectedRunRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def replace_all(self, rows: list[ExpectedRun]) -> None:
        """Replace the entire expected-runs table with ``rows``.

        This requires DELETE privilege on ``private.expected_runs``, which
        ``automation_worker`` is not granted. It is therefore run only under
        the developer login during install, never by a cron job.
        """
        with self._conn.cursor() as cur:
            cur.execute("delete from private.expected_runs")
            for row in rows:
                cur.execute(
                    """
                    insert into private.expected_runs (job_name, agent, max_gap_minutes, schedule)
                    values (%s, %s, %s, %s)
                    """,
                    (row.job_name, row.agent, row.max_gap_minutes, row.schedule),
                )

    def all(self) -> list[ExpectedRun]:
        """Return every configured expected run."""
        with self._conn.cursor() as cur:
            cur.execute(
                "select job_name, agent, max_gap_minutes, schedule from private.expected_runs"
            )
            return [ExpectedRun(*row) for row in cur.fetchall()]
