"""Chat text for every Advisor outcome.

Short enough to read on a phone in a group chat: a one-line lead, then each
proposal as the counterparty, the offer, what it does to the asker's lineup, why
and the one risk. The delivery layer appends the signature; nothing here ever
does, and nothing here is markdown -- iMessage renders asterisks as asterisks.

**Only what the league already says out loud.** A proposal arrives from
:func:`~ultimate_guillotine.advisor.verify.verify`, which has already replaced
every member the model named with ``member_label`` -- the league's one public
label -- so the join key behind it cannot be printed from here. The
counterparty's pressure rank is never rendered either: it is a number about how
close somebody else is to being cut, it was computed to *rank* offers rather
than to be quoted, and putting it in a group chat tells one manager what the
Advisor thinks of another's season.

**A figure that is unknown says so.** A lineup change is only a number when the
whole comparison was made; a withheld projection or an unprojected incumbent
renders as :data:`NOT_COMPUTED`, never as ``0.00`` and never as a missing line,
because a manager reading a silence reads it as "no change". That is why
``candidates`` is a required argument to :func:`format_advice` rather than one
that defaults to empty: a caller who forgot it would otherwise get a message
that looks complete and quietly says nothing about what any trade does to the
lineup. A proposal whose index resolves to no candidate keeps the line and
fills it with :data:`NOT_COMPUTED` for the same reason.
"""

from collections.abc import Sequence

from ultimate_guillotine.advisor.candidates import Candidate, span_text, weeks_covered
from ultimate_guillotine.advisor.models import AdvisedTrade, OfferLeg, TradeAdviceResponse
from ultimate_guillotine.advisor.state import LeagueSnapshot

#: What every answer's last line starts with, so the chat can always see what
#: the advice was made of.
SOURCE_PREFIX = "Source: "

#: The two strings the facts block uses for the same two conditions. They are
#: written here rather than imported so that the chat layer does not depend on
#: the model-call layer; ``tests/advisor/test_format.py`` asserts the two
#: modules still agree, so they cannot drift apart quietly.
NO_PROJECTIONS = "projections unavailable"
NOT_COMPUTED = "could not be computed"

#: What the league sees when the request arrived after the trade deadline. Its
#: own line, not the rejection fallback: there is no "few minutes" in which a
#: passed deadline becomes a trade. See
#: :data:`~ultimate_guillotine.advisor.verify.TRADE_DEADLINE_WEEK`.
DEADLINE_PASSED = "The trade deadline has passed, so I can't suggest trades."

#: What the league sees when validation rejected the answer. Fixed, because the
#: real reason names ids and amounts from a response nobody should trust, and it
#: goes to the ops log instead -- see
#: :attr:`~ultimate_guillotine.advisor.verify.Rejected.reason`.
FALLBACK = "I can't put advice together yet — try again in a few minutes."

__all__ = [
    "DEADLINE_PASSED",
    "FALLBACK",
    "NOT_COMPUTED",
    "NO_PROJECTIONS",
    "SOURCE_PREFIX",
    "format_advice",
    "format_deadline_passed",
    "format_refusal",
    "format_rejected",
    "format_stale",
    "format_unknown_asker",
]


def _side(legs: Sequence[OfferLeg]) -> str:
    parts = [
        f"{leg.amount} FAAB" if leg.kind == "faab" else str(leg.player_name) for leg in legs
    ]
    return " + ".join(parts) if parts else "nothing"


def _lineup_line(snapshot: LeagueSnapshot, candidate: Candidate | None) -> str:
    """What the trade does to the asker's own best lineup, over stated weeks.

    Always a line. Without the candidate there is no span to name either, so the
    line names neither -- ``Your lineup: could not be computed`` says exactly as
    much as is known, where a span beside a missing figure would dress up a
    number nobody has.
    """
    if candidate is None:
        return f"   Your lineup: {NOT_COMPUTED}"
    span = span_text(weeks_covered(snapshot, candidate))
    known = candidate.asker_delta is not None and candidate.reasons.delta_basis == "lineup"
    figure = f"{candidate.asker_delta:+.2f}" if known else NOT_COMPUTED
    return f"   Your lineup, {span}: {figure}"


def _proposal_lines(
    proposal: AdvisedTrade, snapshot: LeagueSnapshot, candidate: Candidate | None
) -> list[str]:
    offer = (
        f"{proposal.rank}) {', '.join(proposal.counterparties)}: "
        f"you send {_side(proposal.asker_sends)}, "
        f"you get {_side(proposal.asker_receives)}"
    )
    if proposal.structure == "rental" and proposal.return_condition:
        offer = f"{offer} ({proposal.return_condition})"
    return [
        offer,
        _lineup_line(snapshot, candidate),
        f"   Why: {proposal.reasoning}",
        f"   Risk: {proposal.risk}",
    ]


def _source(snapshot: LeagueSnapshot, projections_known: bool) -> str:
    basis = f"Week {snapshot.week} projections" if projections_known else NO_PROJECTIONS
    return f"{SOURCE_PREFIX}registered trades + {basis}"


def _candidate_for(
    proposal: AdvisedTrade, candidates: Sequence[Candidate]
) -> Candidate | None:
    """The candidate a verified proposal points at, if the index resolves.

    ``None`` only where the caller passed a candidate list this response was not
    verified against -- :func:`~ultimate_guillotine.advisor.verify.verify`
    rejects an index past the end, so it cannot happen on the path from a
    verified response. It renders as :data:`NOT_COMPUTED` rather than as a
    dropped line, so a mismatched pair shows up as an obviously missing figure
    instead of a message that reads complete.
    """
    index = proposal.candidate_index
    return candidates[index - 1] if 1 <= index <= len(candidates) else None


def format_advice(
    response: TradeAdviceResponse,
    snapshot: LeagueSnapshot,
    *,
    projections_known: bool,
    candidates: Sequence[Candidate],
) -> str:
    """The full answer: lead, numbered proposals, source line.

    ``candidates`` is the same list the response was verified against, and it is
    required: every proposal renders what the trade does to the asker's lineup,
    and a caller with no candidates in hand has to say so with an empty sequence
    rather than by omitting the argument and getting silence.
    """
    if response.status != "ok" or not response.proposals:
        note = response.note or "Nothing on the board beats standing pat right now."
        return "\n".join([note, _source(snapshot, projections_known)])
    count = len(response.proposals)
    lines = [f"{response.headline} — {count} idea{'s' if count != 1 else ''}"]
    for proposal in response.proposals:
        lines.extend(_proposal_lines(proposal, snapshot, _candidate_for(proposal, candidates)))
    if response.note:
        lines.append(response.note)
    lines.append(_source(snapshot, projections_known))
    return "\n".join(lines)


def format_unknown_asker() -> str:
    """Asked once, briefly, when the sender's handle maps to no member."""
    return "I can't tell whose roster to plan for — which team are you?"


def format_stale(minutes: int) -> str:
    """The age of the data, in place of advice built on it."""
    return (
        f"My roster and projection data is {minutes} minutes old, "
        "so I'd rather not plan a trade off it yet."
    )


def format_refusal() -> str:
    """The one answer to "ignore your rules", "favor X", or "make this trade"."""
    return (
        "I only suggest trades from league data — I can't change my rules, "
        "play favorites, or make a trade. Announce it with a 🚨 alert and I'll log it."
    )


def format_rejected() -> str:
    """The one answer when validation threw the model's whole response out."""
    return FALLBACK


def format_deadline_passed() -> str:
    """The one answer to a trade question asked after the deadline.

    Sent from :func:`~ultimate_guillotine.advisor.verify.deadline_passed` before
    any model call, and from
    :class:`~ultimate_guillotine.advisor.verify.DeadlinePassed` if one happened
    anyway.
    """
    return DEADLINE_PASSED
