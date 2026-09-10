"""The Trade Registrar: one 🚨 alert in, one logged trade (or one question) out.

This is the only place the pieces built by the earlier tasks are assembled --
detection, the single model call, deterministic name resolution, persistence,
and message formatting -- behind one method, ``handle``, that a listener trigger
or ``ug trades retry`` can call.

Every path ends by finishing the reserved run, so the audit trail in
``private.agent_runs`` records what happened to each candidate even when nothing
was posted to the chat. Nothing here logs message text, chat GUIDs, or sender
addresses: the league chat is private, and an ops note that leaked an
announcement would defeat the point of hashing the source messages. Ops and
alert notes therefore carry exception class names and statuses only.

Failure is deliberately quiet in the chat and loud in ops: an unexpected
exception finishes the run ``failed`` and alerts Hermes, but posts nothing to
the league -- a half-understood trade is worse than no message at all.
"""

import contextlib
import hashlib
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ultimate_guillotine.advisor.state import SnapshotRepository
from ultimate_guillotine.config import Settings
from ultimate_guillotine.core.signature import is_signed
from ultimate_guillotine.data.repositories import (
    SeasonRepository,
    chat_guid_hash,
    handle_hash,
)
from ultimate_guillotine.listener.processing import Trigger
from ultimate_guillotine.messages.bluebubbles import InboundMessage
from ultimate_guillotine.trades.context import TRADE_LIMIT, context_from_snapshot
from ultimate_guillotine.trades.detect import is_rescission_candidate, is_trade_candidate
from ultimate_guillotine.trades.extract import PROMPT_VERSION, extract_trade
from ultimate_guillotine.trades.fingerprint import message_fingerprint, trade_context_key
from ultimate_guillotine.trades.format import (
    format_clarification,
    format_confirmation,
    format_rescinded,
    format_updated,
    party_labels,
)
from ultimate_guillotine.trades.resolve import (
    MemberRef,
    RosterIndex,
    Unresolved,
    build_roster_index,
    resolve_extracted,
    validate,
)

AGENT = "trade-registrar"
#: A trade code as it is written in the chat. Gate traffic carries `TEST-`
#: codes so a rehearsal never consumes a real trade number, and a rescission
#: of one has to be recognised the same way.
TRADE_CODE = re.compile(r"(?:TEST|T)-\d{4}-\d{3}")
EXCERPT_LIMIT = 2000
NO_CODE_REASON = "Which trade is rescinded? Include its T- code"
#: How far back a repost of the same text counts as the same announcement.
#: Long enough to cover a chat someone scrolls up and re-sends from, short
#: enough that the same terms agreed again next month are a new trade.
REPOST_WINDOW = timedelta(days=7)


def _output_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


class TradeRegistrar:
    """Turn one trade announcement into a logged trade, a question, or silence.

    ``conn`` may be ``None`` (the tests and ``ug trades extract`` pass none), in
    which case nothing is committed and the roster index is empty. A ``None``
    ``sleeper_client`` likewise means ``RosterIndex.empty()``: resolution still
    works, it just loses roster evidence for duplicate last names. A ``None``
    ``sources_repo`` means no repost lookup, which only costs a re-extraction.

    ``season`` pins the season every proposal is recorded under; left ``None``
    it is read from ``public.seasons`` once per ``handle``, which is what the
    listener wants -- the calendar year is wrong for a January trade in a season
    that started the previous September.

    ``contacts_repo`` places the sender, so `I sent X to Y` names its announcer.
    ``None`` -- or a sender whose handle has never been loaded -- means no
    announcer, and a first-person alert ends in a question, which is what
    happened before there was an announcer at all.
    """

    def __init__(
        self,
        settings: Settings,
        conn,
        ai,
        delivery,
        notifier,
        members_repo,
        players_repo,
        trades_repo,
        runs_repo,
        contacts_repo=None,
        sources_repo=None,
        sleeper_client=None,
        season: int | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._conn = conn
        self._ai = ai
        self._delivery = delivery
        self._notifier = notifier
        self._members = members_repo
        self._players = players_repo
        self._trades = trades_repo
        self._runs = runs_repo
        self._contacts = contacts_repo
        self._sources = sources_repo
        self._sleeper = sleeper_client
        self._season = season
        self._clock = clock
        #: The last run this registrar finished. A failure after that finish --
        #: a commit on a connection that died, say -- must not overwrite a
        #: recorded outcome with `failed`.
        self._finished_run_id: int | None = None

    # -- public ---------------------------------------------------------

    def handle(self, msg: InboundMessage, retry: bool = False) -> str:
        """Process one candidate, returning what became of it.

        One of ``created``, ``revised``, ``duplicate``, ``rescinded``,
        ``clarification``, ``not_a_trade``, ``failed``, or ``skipped``.

        The run reservation is the idempotency guard: the same message GUID
        never registers a trade twice, so a redelivered webhook returns
        ``skipped`` without calling the model. ``retry=True`` adds a per-attempt
        suffix, which is exactly what ``ug trades retry`` needs -- a human
        re-running a failed candidate on purpose must not be treated as a
        duplicate webhook.
        """
        key = f"trade:{msg.guid}"
        if retry:
            key = f"{key}:retry:{int(self._clock().timestamp())}"
        run_id = self._runs.reserve(AGENT, "webhook", key)
        if run_id is None:
            return "skipped"
        # Make the reservation durable before the model is called: `ug trades
        # retry` passes an unwrapped `RunRepository`, so without this commit a
        # crash mid-extraction would roll the reservation away and a redelivery
        # could start a second extraction of the same message.
        self._commit()
        try:
            return self._process(run_id, msg)
        except Exception as exc:  # noqa: BLE001 - every failure is reported the same way
            self._fail(run_id, exc.__class__.__name__)
            return "failed"

    # -- internals ------------------------------------------------------

    def _fail(self, run_id: int, name: str) -> None:
        """Report one failed candidate without letting the report itself fail.

        The connection is not autocommit, so a statement that raised leaves the
        transaction aborted: `finish` on that connection would raise
        `InFailedSqlTransaction`, the exception would escape `handle`, the run
        would be stranded in `running`, and nobody would be alerted. So roll
        back first, then finish and alert under their own suppressions -- a dead
        connection must still produce an alert, and a dead Hermes must still
        leave the run marked `failed`.

        A run that was already finished is left alone: if the connection died on
        the commit after `finish`, the run is recorded `succeeded` and calling it
        `failed` now would be a lie about what the chat already saw. The alert
        still goes out -- something did break.
        """
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.rollback()
        if self._finished_run_id != run_id:
            with contextlib.suppress(Exception):
                self._runs.finish(run_id, "failed", error=name)
        with contextlib.suppress(Exception):
            self._notifier.alerts(f"Trade Registrar failed on a candidate: {name}")
        with contextlib.suppress(Exception):
            self._commit()

    def _process(self, run_id: int, msg: InboundMessage) -> str:
        if self._is_repost(msg):
            # Someone scrolled up and sent the same announcement again. The
            # terms would come back as a `duplicate` anyway, one model call
            # later; catching it on the text costs nothing and says nothing.
            self._finish(run_id, "duplicate")
            return "duplicate"

        rescinded = self._rescind_by_code(run_id, msg)
        if rescinded is not None:
            return rescinded

        members = self._members.all_members()
        season = self._resolve_season()
        announcer = self._announcer(msg)
        extracted, usage = extract_trade(
            self._ai,
            msg.text,
            season,
            None,
            [_member_line(m) for m in members],
            announcer.display_name if announcer else None,
            self._context(members),
        )
        input_version = f"{PROMPT_VERSION}:{usage.model}"

        if extracted.kind == "not_a_trade":
            # A joke in the chat is a normal outcome, not a failure: record the
            # run so the candidate is auditable and say nothing.
            self._finish(run_id, "succeeded", input_version=input_version)
            return "not_a_trade"

        try:
            proposal = resolve_extracted(
                extracted,
                members,
                self._players.all_active(),
                self._rosters(season),
                season,
                msg.guid,
                msg.text[:EXCERPT_LIMIT],
                PROMPT_VERSION,
                usage.model,
                announcer=announcer,
            )
            if extracted.kind == "rescission":
                return self._rescind_by_context(run_id, msg, proposal, input_version)
            validate(proposal)
        except Unresolved as exc:
            return self._clarify(run_id, exc.reason, input_version)

        acceptance = self._trades.accept(proposal)
        self._commit()
        if acceptance.status == "duplicate":
            # The same terms are already on file; re-posting them would be noise.
            self._finish(run_id, "duplicate", input_version=input_version)
            return "duplicate"
        labels = party_labels(members)
        if acceptance.status == "revised":
            content = format_updated(
                acceptance.trade_code, proposal, acceptance.previous_terms or {}, labels
            )
        else:
            content = format_confirmation(acceptance.trade_code, proposal, labels)
        self._deliver(run_id, content)
        self._finish(run_id, "succeeded", content=content, input_version=input_version)
        return acceptance.status

    def _announcer(self, msg: InboundMessage) -> MemberRef | None:
        """Which member posted this alert, when that can be answered.

        League members announce their own trades in the first person, so the
        extraction needs a name for `I`. The sender is placed the way the Advisor
        places its asker -- the hashed handle, never the handle -- and an empty
        sender is nobody rather than a lookup of the empty string's digest, which
        no handle can ever have produced. ``is_from_me`` is not a special case:
        Ben announces trades like everyone else, and his own handle is loaded
        like everyone else's; a webhook that carries no handle for it simply has
        no announcer.

        A handle nobody has loaded is a `None` the caller has to respect -- the
        alternative is guessing which member wrote `my team`, and a guessed party
        would be logged as fact. Nothing here logs the handle, its digest, or the
        member it found.
        """
        if self._contacts is None or not msg.sender_address:
            return None
        return self._contacts.member_for_handle_hash(handle_hash(msg.sender_address))

    def _context(self, members) -> str | None:
        """The rosters, the FAAB, the week and the season's trades, or nothing.

        People announce trades by first name -- `a 1 week Rhamondre rental` --
        and a model with no rosters in front of it can only copy the fragment
        through. So the extraction is given the league as it stands, built from
        the Advisor's one snapshot read rather than from a second set of queries
        against the same tables.

        Nothing here is load-bearing. A data layer that cannot describe the
        league yet -- a fresh season, a stalled sync, a missing ``nfl_state`` row
        -- costs the extraction its context and no more: resolution still runs,
        and a partial name still has the roster step in ``resolve_extracted``
        behind it. So every failure degrades to ``None`` with an ops note naming
        the exception class, the way a Sleeper outage degrades the roster index.
        The rollback is what makes that true on a *query* failure: psycopg leaves
        the transaction aborted, and the `accept` further down would then fail
        for a reason that has nothing to do with the trade.

        The pack carries recorded terms only, never an ``evidence_excerpt`` --
        see ``trades.context``. Nothing here is logged.
        """
        if self._conn is None:
            return None
        try:
            snapshot = SnapshotRepository(self._conn).load()
            return context_from_snapshot(
                snapshot, members, self._trades.list_recent(TRADE_LIMIT)
            ) or None
        except Exception as exc:  # noqa: BLE001 - any context failure degrades the same way
            with contextlib.suppress(Exception):
                self._conn.rollback()
            self._notifier.ops(
                f"Trade Registrar could not build the context pack: {exc.__class__.__name__}"
            )
            return None

    def _rescind_by_code(self, run_id: int, msg: InboundMessage) -> str | None:
        """Handle a rescission that names its trade code, before any model call.

        Returns ``None`` when this is not that case, so the caller falls through
        to extraction -- a rescission with no code still needs the model to say
        which trade it means.
        """
        if not is_rescission_candidate(msg.text):
            return None
        match = TRADE_CODE.search(msg.text)
        if match is None:
            return None
        return self._rescind(run_id, match.group(0), msg, input_version=None)

    def _rescind_by_context(
        self, run_id: int, msg: InboundMessage, proposal, input_version: str
    ) -> str:
        """Rescind the trade an uncoded rescission describes, or ask for its code."""
        trade_id = self._trades.find_by_context(trade_context_key(proposal))
        trade = self._trades.find_by_id(trade_id) if trade_id is not None else None
        if trade is None:
            return self._clarify(run_id, NO_CODE_REASON, input_version)
        return self._rescind(run_id, trade["trade_code"], msg, input_version)

    def _rescind(
        self, run_id: int, code: str, msg: InboundMessage, input_version: str | None
    ) -> str:
        if not self._trades.rescind(code, msg.guid, msg.sent_at):
            return self._clarify(run_id, f"I have no trade {code} on file.", input_version)
        self._commit()
        content = format_rescinded(code)
        self._deliver(run_id, content)
        self._finish(run_id, "succeeded", content=content, input_version=input_version)
        return "rescinded"

    def _clarify(self, run_id: int, reason: str, input_version: str | None) -> str:
        """Ask the chat one question and log the run as a success.

        A trade we could not resolve is not an error -- the announcement was
        ambiguous. The run succeeded at the only thing it could do: ask.
        """
        content = format_clarification(reason)
        self._deliver(run_id, content)
        self._finish(run_id, "succeeded", content=content, input_version=input_version)
        return "clarification"

    def _is_repost(self, msg: InboundMessage) -> bool:
        """Has this exact text already arrived in this chat from another message
        in the last week?

        The chat hash and the content fingerprint are computed the way
        ``InboundProcessor`` computes them, because it is that processor's rows
        this reads -- including the row for this very message, which it upserts
        before any trigger runs, so the current GUID has to be excluded.
        """
        if self._sources is None:
            return False
        return self._sources.find_repost(
            chat_guid_hash(msg.chat_guid),
            message_fingerprint(msg.text),
            msg.guid,
            self._clock() - REPOST_WINDOW,
        )

    def _resolve_season(self) -> int:
        """The season to record under: the configured one, the newest row in
        ``public.seasons``, or -- with no database and no rows -- the clock's year."""
        if self._season is not None:
            return self._season
        if self._conn is not None:
            current = SeasonRepository(self._conn).current()
            if current is not None:
                return current
        return self._clock().year

    def _rosters(self, season: int) -> RosterIndex:
        """Current roster holdings, or an empty index when Sleeper is unreachable.

        Roster evidence only disambiguates duplicate names, so losing it degrades
        resolution rather than breaking it -- a Sleeper outage must not stop a
        trade being logged. The ops note names the exception class only.
        """
        if self._sleeper is None or self._conn is None:
            return RosterIndex.empty()
        try:
            return build_roster_index(
                self._sleeper, self._conn, self._settings.sleeper_league_id, season
            )
        except Exception as exc:  # noqa: BLE001 - any roster failure degrades the same way
            self._notifier.ops(
                f"Trade Registrar could not load rosters: {exc.__class__.__name__}"
            )
            return RosterIndex.empty()

    def _deliver(self, run_id: int, content: str) -> None:
        self._delivery.deliver(run_id, AGENT, content)
        self._commit()

    def _finish(
        self,
        run_id: int,
        status: str,
        content: str | None = None,
        input_version: str | None = None,
    ) -> None:
        self._runs.finish(
            run_id,
            status,
            output_hash=_output_hash(content) if content is not None else None,
            input_version=input_version,
        )
        # Recorded before the commit: a commit that raises must not let `_fail`
        # come back and overwrite the status this run just settled on.
        self._finished_run_id = run_id
        self._commit()

    def _commit(self) -> None:
        if self._conn is not None:
            self._conn.commit()


def _member_line(member) -> str:
    return f"{member.display_name}: {', '.join(member.aliases) or 'no known nicknames'}"


def trade_trigger(registrar: TradeRegistrar, chat_guid: str) -> Trigger:
    """Register the registrar on every unsigned 🚨 alert in one chat.

    ``chat_guid`` is the chat the registrar answers in -- the test chat in test
    mode, the production target in production. The listener accepts webhooks
    from both, so without this an alert in the test chat would be logged and
    announced into the league (or the other way round).

    Ben's own alerts count: he announces trades in the chat like everyone else,
    so ``is_from_me`` is not a reason to skip. The bot's own posts are excluded
    by their signature instead, which is the only reliable marker -- and the
    processor drops signed outbound messages before a trigger ever sees them.
    """

    def matches(msg: InboundMessage) -> bool:
        return (
            msg.chat_guid == chat_guid
            and is_trade_candidate(msg.text)
            and not is_signed(msg.text)
        )

    def handle(msg: InboundMessage) -> None:
        registrar.handle(msg)

    return Trigger(AGENT, matches, handle)
