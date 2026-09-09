"""The Trade Advisor: one tagged question in, two or three proposals out.

This is where the deterministic pipeline built by the earlier tasks is
assembled -- the league snapshot, the scores, the priced candidates -- around
exactly one model call, with the answer checked back against those candidates
before a word of it reaches the chat. Every path finishes the run it reserved,
so ``private.agent_runs`` records what happened to a question even when nothing
was sent.

**The gates run in order, and the cheap ones run first.** An attempt to steer
the Advisor, a sender the league cannot place, a snapshot that is missing or
stale, and a question asked after the trade deadline are each answered from one
fixed line without paying for a model call at all. Only a question that clears
all four is priced.

**The gates are one method, and everything that answers a question goes through
it.** :meth:`TradeAdvisor.answer_message` is the whole guarded pipeline; the
listener wraps it in a reserved run and a delivery, and ``ug advisor ask`` wraps
it in nothing at all. Neither one re-implements a gate, so a dry run cannot be
handed a question the chat would have been refused -- which is what a second
entry point drifting from the first would eventually allow.

**One model call per question, and none at all where there is nothing to ask
about.** A question the candidate generator answers with an empty board is
answered from one fixed line: a model handed no candidates can only invent one.
The single retry inside
:class:`~ultimate_guillotine.ai.hermes.HermesStructuredClient` is the only retry
there is: a second :func:`~ultimate_guillotine.advisor.prompt.advise` would be a
second, possibly different answer to one question, charged twice, with a group
chat waiting on the listener's single-flight lock the whole time. An answer that
does not survive :func:`~ultimate_guillotine.advisor.verify.verify` is declined,
not re-asked.

**There is no lock here on purpose.** ``listener/app.py`` already processes
every webhook under one lock, so a second question in the same chat is answered
after the first finishes and never beside it. Do not add a second one.

**Nothing here logs message text, chat GUIDs, or sender addresses.** The league
chat is private and the sender is matched by hash, so ops and alert notes carry
statuses, exception class names, and validation reasons only -- and the chat, in
return, only ever sees the fixed lines in
:mod:`~ultimate_guillotine.advisor.format`, never a reason written for ops.
"""

import contextlib
import hashlib
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import NamedTuple

from ultimate_guillotine.advisor.candidates import Candidate, generate_candidates
from ultimate_guillotine.advisor.detect import is_advice_request, is_injection_attempt, parse_ask
from ultimate_guillotine.advisor.format import (
    STAND_PAT,
    format_advice,
    format_deadline_passed,
    format_refusal,
    format_rejected,
    format_rejection,
    format_stale,
    format_unknown_asker,
)
from ultimate_guillotine.advisor.models import TradeAdviceResponse
from ultimate_guillotine.advisor.pricing import PricePoint, price_points
from ultimate_guillotine.advisor.prompt import PROMPT_VERSION, advise
from ultimate_guillotine.advisor.scoring import score_league
from ultimate_guillotine.advisor.state import (
    LAST_REGULAR_WEEK,
    LeagueSnapshot,
    SnapshotUnavailable,
)
from ultimate_guillotine.advisor.verify import Rejected, deadline_passed, verify
from ultimate_guillotine.config import Settings
from ultimate_guillotine.core.signature import is_signed
from ultimate_guillotine.data.repositories import handle_hash
from ultimate_guillotine.listener.processing import Trigger
from ultimate_guillotine.messages.bluebubbles import InboundMessage
from ultimate_guillotine.trades.models import MemberRef

AGENT = "trade-advisor"

#: How many seasons of price history one run reads: this one and the last. Two
#: is enough for a comparable to exist at every position without quoting a price
#: from a league that no longer plays the same rules.
HISTORY_SEASONS = 2


class Answer(NamedTuple):
    """One finished answer: what became of the question, what the chat sees, and
    which model said it.

    ``model`` is ``None`` on every path that never called one -- an empty
    candidate set, a withheld projection -- and it is returned rather than left
    on the advisor, so two questions answered by one advisor cannot read each
    other's model and ``ug advisor ask`` can print the model that answered it
    without reaching into a private attribute.
    """

    outcome: str
    text: str
    model: str | None


def _output_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _input_version(model: str | None) -> str | None:
    """What produced this run's output, or ``None`` when no model did.

    The prompt version and the model that answered, together, so a later
    regression is traceable to whichever of the two changed.
    """
    return None if model is None else f"{PROMPT_VERSION}:{model}"


class TradeAdvisor:
    """Answer one advice question, or say plainly why it cannot.

    ``conn`` may be ``None`` -- the tests and ``ug advisor ask`` pass none -- in
    which case nothing is committed, which is exactly what a dry run wants. So
    may ``settings``: nothing on the answering path reads them, and the dry run
    against the fixture league has no configured league to read them from.

    The repositories are the listener's own: ``contacts_repo`` maps a hashed
    sender to a member, ``members_repo`` names them, ``snapshots`` reads the
    league, ``prices`` reads what past trades cost, and ``runs_repo`` reserves
    and finishes the run this question is recorded as.
    """

    def __init__(
        self,
        settings: Settings | None,
        conn,
        ai,
        delivery,
        notifier,
        contacts_repo,
        members_repo,
        snapshots,
        prices,
        runs_repo,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._conn = conn
        self._ai = ai
        self._delivery = delivery
        self._notifier = notifier
        self._contacts = contacts_repo
        self._members = members_repo
        self._snapshots = snapshots
        self._prices = prices
        self._runs = runs_repo
        self._clock = clock
        #: The last run this advisor finished. A failure *after* that finish --
        #: a commit on a connection that has since died -- must not overwrite a
        #: recorded outcome with ``failed``.
        self._finished_run_id: int | None = None

    # -- public ---------------------------------------------------------

    def handle(self, msg: InboundMessage) -> str:
        """Process one advice request, returning what became of it.

        One of ``ok``, ``no_good_trades``, ``insufficient_data``,
        ``unknown_asker``, ``stale``, ``refused``, ``rejected``, ``failed``, or
        ``skipped``.

        The run reservation is the idempotency guard: a redelivered webhook
        carries the same message GUID, reserves nothing, and returns ``skipped``
        without reading the league or calling the model.
        """
        run_id = self._runs.reserve(AGENT, "webhook", f"advisor:{msg.guid}")
        if run_id is None:
            return "skipped"
        # Durable before the model is called: a crash mid-answer must leave the
        # reservation behind, so a redelivery is skipped rather than answered
        # twice at the league's expense.
        self._commit()
        try:
            return self._process(run_id, msg)
        except Exception as exc:  # noqa: BLE001 - every failure is reported alike
            self._fail(run_id, exc.__class__.__name__)
            return "failed"

    def candidates_for(
        self, snapshot: LeagueSnapshot, asker_member_id: int, text: str
    ) -> list[Candidate]:
        """The candidate set this question would put in front of the model.

        Public because it is the answer to "why did it suggest that?": the CLI
        prints it and the tests answer with it, so neither has to guess at what
        the pipeline generated.
        """
        ask = parse_ask(text, self._ask_names(snapshot))
        return generate_candidates(
            snapshot,
            score_league(snapshot),
            asker_member_id,
            ask,
            self._price_points(snapshot),
        )

    def gate(
        self, text: str, member: MemberRef | None, now: datetime | None = None
    ) -> tuple[Answer | None, LeagueSnapshot | None]:
        """Every check that runs before a question is priced, and nothing else.

        Returns the refusal and no snapshot, or no refusal and the snapshot the
        question is to be answered against. Split out of
        :meth:`answer_message` so that ``ug advisor ask --json``, which never
        reaches a model and so never reaches ``answer_message``, still runs the
        identical guards in the identical order rather than a second copy of
        them that could drift.

        The gates run cheapest first -- a hostile message is answered from its
        own text, before a sender is placed, before the league is read and long
        before a model is asked anything.
        """
        if is_injection_attempt(text):
            # Answered from the text alone: an attempt to overrule the Advisor
            # or to have it commit a trade never reaches the model, and never
            # reaches the league data either.
            return Answer("refused", format_refusal(), None), None
        if member is None:
            return Answer("unknown_asker", format_unknown_asker(), None), None

        snapshot = self._snapshots.load(horizon_weeks=horizon_weeks(text))
        moment = self._clock() if now is None else now
        if snapshot.is_stale(moment):
            minutes = int(snapshot.age(moment).total_seconds() // 60)
            return Answer("stale", format_stale(minutes), None), None
        if snapshot.team_for_member(member.member_id) is None:
            # The member is known but has no team this season, so there is no
            # roster to plan for and nothing to guess from.
            return Answer("unknown_asker", format_unknown_asker(), None), None
        if deadline_passed(snapshot):
            # Checked here rather than left to `verify`, so a question asked
            # after the deadline costs nothing.
            return Answer("rejected", format_deadline_passed(), None), None
        return None, snapshot

    def answer_message(
        self, text: str, member: MemberRef | None, now: datetime | None = None
    ) -> Answer:
        """One question, every gate, no side effects: the guarded entry point.

        The listener calls this with the member a hashed handle resolved to and
        ``ug advisor ask`` calls it with the member named on the command line;
        neither adds a check of its own, so the dry run refuses exactly what the
        chat refuses.

        The snapshot is loaded in :meth:`gate` rather than passed in, so a
        refused or unplaceable question never touches the league data at all;
        :class:`~ultimate_guillotine.advisor.state.SnapshotUnavailable` is left
        to the caller, because "the data layer is down" is an operational answer
        and the two callers give it differently. ``now`` defaults to this
        advisor's clock.
        """
        refusal, snapshot = self.gate(text, member, now)
        if refusal is not None or snapshot is None or member is None:
            # `gate` returns a snapshot only when it has placed the member and
            # found nothing to refuse, so the second two are unreachable and
            # spelled out rather than asserted.
            return refusal or Answer("unknown_asker", format_unknown_asker(), None)
        return self.answer(snapshot, member.member_id, text)

    def answer(self, snapshot: LeagueSnapshot, asker_member_id: int, text: str) -> Answer:
        """The priced half of the pipeline, for a question that cleared the gates.

        No run, no delivery, no commit. Callers that start from a message want
        :meth:`answer_message`, which runs the gates and then this; this one is
        public for the tests that drive the pricing directly. The outcome is one
        of ``ok``,
        ``no_good_trades``, ``insufficient_data`` or ``rejected``;
        :class:`~ultimate_guillotine.ai.structured.AIUnavailable` and
        :class:`~ultimate_guillotine.ai.structured.AIInvalidOutput` are left to
        the caller, because a model outage is not an answer.
        """
        ask = parse_ask(text, self._ask_names(snapshot))
        scores = score_league(snapshot)
        points = self._price_points(snapshot)
        candidates = generate_candidates(snapshot, scores, asker_member_id, ask, points)
        known = snapshot.coverage_ok()

        if ask.wants_numbers and not known:
            # The question is about a projected number and there is no projected
            # number to give. Nothing a model could add would be honest.
            response = _insufficient(
                "This week's projections haven't synced, so I can't compare the numbers."
            )
            return Answer(
                "insufficient_data", self._render(response, snapshot, candidates, known), None
            )

        if not candidates:
            # Nothing honest to choose between, so there is nothing to ask about:
            # a model handed an empty set can only invent one. The league gets
            # the one true sentence instead, and the run costs nothing.
            return Answer(
                "no_good_trades",
                self._render(_stand_pat(), snapshot, candidates, known),
                None,
            )

        response, usage = advise(
            self._ai, snapshot, scores, asker_member_id, ask, candidates, points
        )
        try:
            checked = verify(response, candidates, snapshot, asker_member_id)
        except Rejected as exc:
            # One `except`, and the sentence it earns is chosen by the exception
            # rather than by the order of two clauses -- see `format_rejection`.
            self._notifier.ops(f"Trade Advisor declined an answer: {exc.reason}")
            return Answer("rejected", format_rejection(exc), usage.model)
        return Answer(
            checked.status, self._render(checked, snapshot, candidates, known), usage.model
        )

    # -- internals ------------------------------------------------------

    def _process(self, run_id: int, msg: InboundMessage) -> str:
        """The message half: place the sender, answer through the gates, reply.

        A webhook with no sender is nobody, and hashing the empty string would
        look up a digest no handle can ever have produced -- so an empty sender
        is passed on as the unplaceable member it is, without a lookup.
        """
        member = (
            self._contacts.member_for_handle_hash(handle_hash(msg.sender_address))
            if msg.sender_address
            else None
        )
        try:
            answer = self.answer_message(msg.text, member)
        except SnapshotUnavailable as exc:
            # The only outcome the chat and the terminal word differently: ops
            # hears the reason, the league hears the fallback line.
            self._notifier.ops(f"Trade Advisor has no snapshot: {exc.reason}")
            return self._respond(run_id, "insufficient_data", format_rejected())
        return self._respond(
            run_id, answer.outcome, answer.text, _input_version(answer.model)
        )

    def _render(
        self,
        response: TradeAdviceResponse,
        snapshot: LeagueSnapshot,
        candidates: Sequence[Candidate],
        known: bool,
    ) -> str:
        return format_advice(
            response, snapshot, projections_known=known, candidates=candidates
        )

    def _ask_names(self, snapshot: LeagueSnapshot) -> list[str]:
        """Every name a counterparty may be named by in one question.

        Both of the snapshot's strings for each team -- the label the league
        renders and the join key behind it, either of which
        :meth:`LeagueSnapshot.team_by_name` resolves -- and the member roster
        besides, so a manager with no team row this season is still read as a
        name rather than as an ordinary word in the sentence.
        """
        names = [
            name for team in snapshot.teams for name in (team.member_label, team.display_name)
        ]
        names.extend(member.display_name for member in self._members.all_members())
        return list(dict.fromkeys(names))

    def _price_points(self, snapshot: LeagueSnapshot) -> list[PricePoint]:
        """What the league has paid at each position, from its own trade log."""
        seasons = [snapshot.season - offset for offset in range(HISTORY_SEASONS)]
        positions = {
            holding.sleeper_player_id: holding.position
            for team in snapshot.teams
            for holding in team.holdings
        }
        return price_points(self._prices.accepted_terms(seasons), positions)

    def _respond(
        self, run_id: int, outcome: str, content: str, input_version: str | None = None
    ) -> str:
        """Post one answer and settle the run it belongs to."""
        self._delivery.deliver(run_id, AGENT, content)
        self._commit()
        self._runs.finish(
            run_id,
            "succeeded",
            output_hash=_output_hash(content),
            input_version=input_version,
        )
        # Recorded before the commit: a commit that raises must not let `_fail`
        # come back and overwrite the status this run just settled on.
        self._finished_run_id = run_id
        self._commit()
        return outcome

    def _fail(self, run_id: int, name: str) -> None:
        """Report one failed question without letting the report itself fail.

        The connection is not autocommit, so a statement that raised leaves the
        transaction aborted and ``finish`` on it would raise in turn, stranding
        the run in ``running`` with nobody alerted. So roll back first, then
        finish and alert under their own suppressions: a dead connection must
        still produce an alert, and a dead Hermes must still leave the run
        marked ``failed``. A run that already finished keeps the status the
        chat saw.
        """
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.rollback()
        if self._finished_run_id != run_id:
            with contextlib.suppress(Exception):
                self._runs.finish(run_id, "failed", error=name)
        with contextlib.suppress(Exception):
            self._notifier.alerts(f"Trade Advisor failed on a question: {name}")
        with contextlib.suppress(Exception):
            self._commit()

    def _commit(self) -> None:
        if self._conn is not None:
            self._conn.commit()


def _insufficient(note: str) -> TradeAdviceResponse:
    """An honest empty answer, built here rather than asked of the model."""
    return TradeAdviceResponse(
        status="insufficient_data", headline="Missing data", proposals=[], note=note
    )


def _stand_pat() -> TradeAdviceResponse:
    """The answer to a board with no trade on it, built here for the same reason."""
    return TradeAdviceResponse(
        status="no_good_trades", headline="No trade worth making",
        proposals=[], note=STAND_PAT,
    )


def horizon_weeks(text: str) -> int:
    """How many weeks of projections this question needs read.

    A permanent trade is judged on the snapshot's own week, so one week is the
    whole horizon. A rental is judged on the weeks it covers -- the week it is
    struck in plus the term asked for -- and a week nobody read projections for
    cannot be added to that total, so the read has to be as long as the term.
    An open-ended rental asks for the rest of the season;
    :meth:`SnapshotRepository.load` caps that at the last regular week.

    Parsed with no member names because none of the horizon rules need one: the
    term and the rental language are read off the words alone, and the ask that
    the answer is actually built from is parsed again against the snapshot.
    """
    # Deliberately name-free, per the paragraph above.
    ask = parse_ask(text, ())
    if not ask.rental:
        return 1
    if ask.horizon_weeks is None:
        return LAST_REGULAR_WEEK
    return ask.horizon_weeks + 1


def advisor_trigger(advisor: TradeAdvisor, chat_guid: str) -> Trigger:
    """Fire the Advisor on tagged advice questions in one chat, and nowhere else.

    Three gates, all of them deterministic and all of them ahead of any model
    call. ``chat_guid`` is the one chat the Advisor answers in -- the listener
    accepts webhooks from every registered delivery target, so without this a
    question in the production chat would be answered by a skill that is only
    cleared for the self-test one. The ``@bot`` tag and the advice-versus-lookup
    rule are :func:`~ultimate_guillotine.advisor.detect.is_advice_request`, so a
    factual question routes to the Concierge and the Advisor stays quiet. And
    the bot's own posts are excluded by their signature, which is the only
    reliable marker -- the processor drops signed outbound messages before a
    trigger sees them, and this says so again rather than relying on it.
    """

    def matches(msg: InboundMessage) -> bool:
        return (
            msg.chat_guid == chat_guid
            and is_advice_request(msg.text)
            and not is_signed(msg.text)
        )

    def handle(msg: InboundMessage) -> None:
        advisor.handle(msg)

    return Trigger(AGENT, matches, handle)
