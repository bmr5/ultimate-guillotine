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


# Formatting a human puts in a phone number and an Apple handle never carries:
# spaces, dashes, parentheses, dots. ``+`` and the digits are the handle.
_HANDLE_FORMATTING = " \t\r\n -()."


def normalize_handle(address: str) -> str:
    """Return the canonical form of an Apple handle, before hashing.

    A digest is unforgiving: `" +1 (555) 555-0100 "` and `"+15555550100"` are
    the same phone to a person and two different rows to SHA-256, so the
    commissioner's file would silently fail to match half its senders. Phone
    handles lose their formatting; email handles lose their case, which is the
    only way the same address gets typed two ways.

    This is a no-op for an already-canonical E.164 number, which is what
    BlueBubbles delivers, so every ``private.source_messages.sender_hash``
    already stored still matches what this produces.
    """
    cleaned = address.strip()
    if "@" in cleaned:
        return cleaned.lower()
    return "".join(ch for ch in cleaned if ch not in _HANDLE_FORMATTING)


def handle_hash(address: str) -> str:
    """Return the SHA-256 hex digest of a normalized Apple handle.

    The same digest ``private.source_messages.sender_hash`` holds, so a stored
    sender can be matched against a loaded contact without either side ever
    holding the handle itself.
    """
    return hashlib.sha256(normalize_handle(address).encode()).hexdigest()


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


#: What a member who has left the league is keyed by in ``public.members.display_name``.
#: A live member's ``display_name`` is their Sleeper username, so the prefix is also the
#: guarantee that ``ug sleeper sync`` -- which upserts on that column, and only ever writes
#: names Sleeper handed it -- can never collide with one of these rows.
FORMER_MEMBER_PREFIX = "former:"


def former_display_name(name: str) -> str:
    """Return the ``public.members.display_name`` key for a departed manager.

    ``display_name`` is unique and not null, so a member without a Sleeper account still
    needs one; it must not be the person's name, because a real name never reaches a public
    page and this column is the one every consumer is told to ignore. The slug is
    ``normalize_name``'s form with its spaces hyphenated, so the same person typed two ways
    (``"A Name"``, ``" a   name "``) lands on one row rather than two.

    Raises ``ValueError`` for a name that normalizes to nothing: ``former:`` on its own is
    not a key, and a blank one would collide with the next blank one.
    """
    slug = normalize_name(name).replace(" ", "-")
    if not slug:
        raise ValueError("a former member needs a name")
    return FORMER_MEMBER_PREFIX + slug


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
                    m.nickname, m.sleeper_display_name
                from public.members m left join private.member_aliases a on a.member_id = m.id
                group by m.id, m.display_name, m.nickname, m.sleeper_display_name order by m.id
                """
            )
            return [
                MemberRef(row[0], row[1], tuple(row[2]), row[3], row[4])
                for row in cur.fetchall()
            ]

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

    def upsert_former(self, name: str, aliases: list[str]) -> tuple[bool, int]:
        """Create (or refresh) a member for somebody who has left the league.

        Returns ``(created, alias count)`` -- ``created`` is False on a rerun, which is the
        whole point: the commissioner types the same command again after remembering
        another nickname and gets one row, not two.

        ``sleeper_display_name`` stays null and no ``public.teams`` row is written, because
        there is no Sleeper account to tie either to. The label the pages show is the
        ``nickname``, and it is published exactly the way every other member's is -- as the
        first alias, through ``replace_aliases`` -- so ``name`` is passed in front of the
        rest and nothing here has its own idea of what a public label is.

        Member row and aliases share one transaction: an alias another member already holds
        raises out of ``replace_aliases``, and a half-made profile (a member with no aliases
        for resolution to match on) is worse than none at all.

        The name's own whitespace is collapsed before either use. The slug already ignores
        the difference (``normalize_name`` collapses), but the nickname does not:
        ``replace_aliases`` only strips its aliases, so a rerun typed with a stray double
        space would land on the same row and republish a double-spaced public label. One
        collapse here keeps the key and the label agreeing on what the name is.
        """
        name = " ".join(name.split())
        display_name = former_display_name(name)
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(
                "select id from public.members where display_name = %s", (display_name,)
            )
            row = cur.fetchone()
            created = row is None
            if row is None:
                cur.execute(
                    """
                    insert into public.members (display_name, nickname, sleeper_display_name)
                    values (%s, %s, null) returning id
                    """,
                    (display_name, name),
                )
                inserted = cur.fetchone()
                if inserted is None:
                    raise RuntimeError("insert returned no id")
            else:
                # sleeper_display_name is renulled rather than left alone: this row is the
                # profile of somebody with no Sleeper account, and that is the column
                # saying so.
                cur.execute(
                    "update public.members set sleeper_display_name = null where id = %s",
                    (row[0],),
                )
            written = self.replace_aliases(display_name, [name, *aliases])
        return created, written

    def count_former(self) -> int:
        """How many members are former members. A count, never the names."""
        with self._conn.cursor() as cur:
            cur.execute(
                "select count(*) from public.members where display_name like %s",
                (FORMER_MEMBER_PREFIX + "%",),
            )
            row = cur.fetchone()
            return 0 if row is None else int(row[0])


class MemberContactRepository:
    """Maps hashed Apple handles to league members.

    ``private.member_contacts.alias`` is deliberately left null: it would hold a
    raw handle, and the whole point of this table is that no raw handle is ever
    written down. Do not start filling it in.
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def member_for_handle_hash(self, digest: str) -> MemberRef | None:
        """Return the member this hashed handle belongs to, or ``None``.

        ``None`` is the answer for anybody the loader has not been told about,
        and the caller has to treat it as such: a sender the Advisor cannot
        match is a sender whose "my roster" it must not guess at.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select m.id, m.display_name,
                    coalesce(array_agg(a.alias) filter (where a.alias is not null), '{}'),
                    m.nickname
                from private.member_contacts c
                join public.members m on m.id = c.member_id
                left join private.member_aliases a on a.member_id = m.id
                where c.handle_hash = %s
                group by m.id, m.display_name, m.nickname
                """,
                (digest,),
            )
            row = cur.fetchone()
            return MemberRef(row[0], row[1], tuple(row[2]), row[3]) if row else None

    def replace_handles(self, member_display_name: str, handle_hashes: list[str]) -> int:
        """Replace a member's hashed handles wholesale, returning how many landed.

        Delete and insert share one savepoint, matching ``replace_aliases``: a
        handle already claimed by somebody else must not leave this member with
        no handles at all and the caller's transaction unusable.
        """
        wanted = list(dict.fromkeys(handle_hashes))
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute(
                "select id from public.members where display_name = %s",
                (member_display_name,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"unknown member: {member_display_name}")
            member_id = row[0]
            cur.execute(
                "select handle_hash from private.member_contacts"
                " where handle_hash = any(%s) and member_id <> %s",
                (wanted, member_id),
            )
            if cur.fetchone() is not None:
                raise ValueError("handle already belongs to another member")
            cur.execute(
                "delete from private.member_contacts where member_id = %s", (member_id,)
            )
            cur.executemany(
                "insert into private.member_contacts (member_id, handle_hash, alias)"
                " values (%s, %s, null)",
                [(member_id, digest) for digest in wanted],
            )
        return len(wanted)

    def counts(self) -> list[tuple[str, int]]:
        """``(display_name, handle count)`` for every member with a contact row."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select m.display_name, count(*)
                from private.member_contacts c
                join public.members m on m.id = c.member_id
                group by m.display_name order by m.display_name
                """
            )
            return [(row[0], row[1]) for row in cur.fetchall()]
