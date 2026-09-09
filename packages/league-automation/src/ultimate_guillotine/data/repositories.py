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
from ultimate_guillotine.trades.models import MemberRef
from ultimate_guillotine.trades.names import normalize_name


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
        input_version: str | None = None,
    ) -> None:
        """Mark a run finished, recording its terminal status.

        ``input_version`` names what produced the run's output -- for the Trade
        Registrar, the prompt version and the model that answered. It is how a
        later regression is traced back to a prompt or model change; runs that
        have no versioned input leave it null.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                update private.agent_runs
                set status = %s, output_hash = %s, error = %s,
                    input_version = coalesce(%s, input_version), finished_at = now()
                where id = %s
                """,
                (status, output_hash, error, input_version, run_id),
            )

    def stale_running(
        self, older_than: timedelta, now: datetime
    ) -> list[tuple[str, str]]:
        """Return ``(agent, idempotency_key)`` for runs still ``running`` since
        longer than ``older_than`` relative to ``now``.

        A run in this state is one whose agent died between reserving it and
        finishing it: nothing was recorded, nothing was said in the chat, and
        the idempotency key names the message a human has to re-run.
        """
        cutoff = now - older_than
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select agent, idempotency_key from private.agent_runs
                where status = 'running' and started_at < %s
                order by id
                """,
                (cutoff,),
            )
            return [(row[0], row[1]) for row in cur.fetchall()]

    def last_finished_status(self, agent: str) -> str | None:
        """The newest terminal status for ``agent``, ignoring runs still running.

        This is the "before" the ops transition notes compare against, which is
        why a ``running`` row is not an answer: the run asking the question is
        itself still running, and it must not read its own reservation as the
        previous verdict.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select status from private.agent_runs
                where agent = %s and status in ('succeeded', 'failed')
                order by id desc limit 1
                """,
                (agent,),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def last_started(self, agent: str) -> datetime | None:
        """Return the most recent ``started_at`` for the given agent, if any."""
        with self._conn.cursor() as cur:
            cur.execute(
                "select max(started_at) from private.agent_runs where agent = %s",
                (agent,),
            )
            row = cur.fetchone()
            return row[0] if row else None


class SeasonRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def current(self) -> int | None:
        """Return the newest season year on file, or ``None`` when there are none.

        The league's season is a row, not the calendar year: a trade announced
        in January belongs to the season that started the previous September.
        """
        with self._conn.cursor() as cur:
            cur.execute("select year from public.seasons order by year desc limit 1")
            row = cur.fetchone()
            return row[0] if row else None

    def exists(self, year: int) -> bool:
        """Is this season on file? Everything a trade is recorded against hangs
        off its season row, so a replay of a season with no row can only fail."""
        with self._conn.cursor() as cur:
            cur.execute("select 1 from public.seasons where year = %s", (year,))
            return cur.fetchone() is not None


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
            if row is None:
                raise RuntimeError("insert returned no id")
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
            if row is None:
                raise RuntimeError("insert returned no id")
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

    def stuck_sending(self, older_than: timedelta, now: datetime) -> list[int]:
        """Return the ids of outbound messages still in ``sending`` whose reservation
        is older than ``older_than`` relative to ``now``.

        A row in this state means a send crossed the Messages boundary without its
        outcome ever being recorded, so the health job reports it for a human.
        """
        cutoff = now - older_than
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select id from private.outbound_messages
                where state = 'sending' and reserved_at < %s
                order by id
                """,
                (cutoff,),
            )
            return [row[0] for row in cur.fetchall()]

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
        existed (by ``source_guid`` or the composite key on
        ``chat_guid_hash``, ``content_fingerprint``, ``sent_at``)."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into private.source_messages
                    (source_guid, chat_guid_hash, sender_hash, direction, sent_at,
                     content_fingerprint, excerpt, trigger_name)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict do nothing
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

    def get(self, source_guid: str) -> SourceMessage | None:
        """Return the recorded message with this GUID, or ``None``.

        The raw chat GUID and sender address were never stored, so a message
        rebuilt from this row carries hashes and an excerpt only -- enough to
        re-run an agent over it, and nothing that identifies the chat.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select source_guid, chat_guid_hash, sender_hash, direction, sent_at,
                       content_fingerprint, excerpt, trigger_name
                from private.source_messages where source_guid = %s
                """,
                (source_guid,),
            )
            row = cur.fetchone()
            return SourceMessage(*row) if row else None

    def find_repost(
        self,
        chat_guid_hash: str,
        fingerprint: str,
        exclude_guid: str,
        since: datetime,
    ) -> bool:
        """Has this chat already carried this exact text, in another message, since
        ``since``?

        Only inbound messages count -- the bot's own posts are outbound -- and
        the message being asked about is excluded by GUID, because the processor
        records it before any agent runs.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select 1 from private.source_messages
                where chat_guid_hash = %s and content_fingerprint = %s
                  and source_guid <> %s and direction = 'inbound' and sent_at >= %s
                limit 1
                """,
                (chat_guid_hash, fingerprint, exclude_guid, since),
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

        This requires DELETE privilege on ``private.expected_runs``. Unlike
        every other table in the private schema, ``automation_worker`` is
        granted DELETE on this one table, because it holds installer-managed
        configuration (the cron schedule), not a league fact: the installer
        runs this under the worker login, never under a cron job.
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


class MemberAliasRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def all_members(self) -> list[MemberRef]:
        """Return every member with the aliases (if any) resolution matches them by."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select m.id, m.display_name,
                    coalesce(array_agg(a.alias) filter (where a.alias is not null), '{}'),
                    m.nickname
                from public.members m left join private.member_aliases a on a.member_id = m.id
                group by m.id, m.display_name, m.nickname order by m.id
                """
            )
            return [MemberRef(row[0], row[1], tuple(row[2]), row[3]) for row in cur.fetchall()]

    def replace_aliases(self, member_display_name: str, aliases: list[str]) -> int:
        """Replace a member's aliases wholesale, returning how many rows were written.

        Also republishes ``public.members.nickname`` as the member's first alias --
        the one label the board and the Concierge are allowed to show. Every other
        alias stays in ``private.member_aliases``.

        Aliases that normalize alike (``Big Ben`` and ``big  ben!``) collapse to
        one row, so the count returned may be smaller than ``len(aliases)``.
        Raises ``ValueError`` when ``member_display_name`` isn't a known member,
        or when an alias is already held by a different member.

        The delete and the inserts run in one savepoint: an alias claimed by
        somebody else would otherwise leave the member with no aliases at all
        and the caller's transaction unusable.
        """
        # First spelling wins for each normalized form; later duplicates drop.
        # Surrounding whitespace is stripped first so the stored alias row and
        # the nickname published from it agree: ``normalize_name`` already
        # strips, so a padded alias would otherwise store one spelling here and
        # publish a differently padded one to ``public.members.nickname``.
        # An entry that is nothing but whitespace is not an alias at all: it would
        # store a blank row nobody can match on and, if it came first, publish an
        # empty string as the member's public label.
        wanted: dict[str, str] = {}
        for alias in aliases:
            trimmed = alias.strip()
            if not trimmed:
                continue
            wanted.setdefault(normalize_name(trimmed), trimmed)

        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(
                "select id from public.members where display_name = %s",
                (member_display_name,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"unknown member '{member_display_name}'")
            member_id = row[0]

            cur.execute("delete from private.member_aliases where member_id = %s", (member_id,))
            for alias_normalized, alias in wanted.items():
                try:
                    cur.execute(
                        """
                        insert into private.member_aliases (member_id, alias, alias_normalized)
                        values (%s, %s, %s)
                        """,
                        (member_id, alias, alias_normalized),
                    )
                except psycopg.errors.UniqueViolation as exc:
                    raise ValueError(
                        f"alias '{alias}' already belongs to another member"
                    ) from exc

            # The first alias in the file's order is the public label. `wanted` is
            # keyed by normalized form but preserves first-appearance order, so this
            # is the member's first alias in its original spelling. An empty list
            # clears the nickname: a member with no aliases has no public label, and
            # consumers fall back to sleeper_display_name.
            cur.execute(
                "update public.members set nickname = %s where id = %s",
                (next(iter(wanted.values()), None), member_id),
            )
        return len(wanted)
