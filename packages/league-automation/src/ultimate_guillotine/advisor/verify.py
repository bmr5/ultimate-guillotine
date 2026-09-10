"""Check the model's answer back against the candidates it was handed.

The schema in :mod:`~ultimate_guillotine.advisor.models` proves the answer is
well formed. This module proves it is *true*: every member, player id, FAAB
amount, structure and trade code has to be one the deterministic pipeline put in
front of the model. A response that invents anything is rejected whole -- not
repaired, not partially used -- and the caller sends
:func:`~ultimate_guillotine.advisor.format.format_rejected` while the reason on
the exception goes to ops.

**The order is deliberate.** Members are resolved first, against the snapshot,
because "who is this?" is answerable without any candidate at all and because an
unknown or eliminated name is the reason worth reporting even when the rest of
the proposal is nonsense too. Only then is ``candidate_index`` looked up, and
only then are the legs compared.

**The comparison is equality, not containment.** A proposal's legs must be
exactly the legs of the candidate it names -- same kinds, same players, same
amounts, same directions, same count. A dropped FAAB leg is not a cheaper
version of the trade and an extra player is not a sweetener; both are trades
nobody generated, priced or checked against a budget.

**The trade deadline is its own outcome.** Past it there is no such thing as a
sound proposal, so :class:`DeadlinePassed` says that rather than letting a
whole-response rejection read like a fabricated answer -- the league hears the
deadline and not "try again in a few minutes", which would be a lie about a week
that is not coming back. Task 9 calls :func:`deadline_passed` *before* the model
and never pays for the call; the raise here is the safety net for a caller that
did not.

**Two things are repaired rather than rejected**: a player's display name and a
rental's return condition. In both cases the fact lives on the candidate -- the
id and the return week -- and the words are decoration the model may respell,
so correcting the decoration beats refusing a sound proposal. Dropping the
return condition entirely is not a respelling, and is rejected.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import NamedTuple

from ultimate_guillotine.advisor.candidates import Candidate, CandidateLeg
from ultimate_guillotine.advisor.models import AdvisedTrade, OfferLeg, TradeAdviceResponse
from ultimate_guillotine.advisor.state import AdvisorTeamState, LeagueSnapshot
from ultimate_guillotine.trades.registrar import TRADE_CODE

#: The last week a trade may be proposed in.
#:
#: One short of :data:`~ultimate_guillotine.advisor.state.LAST_REGULAR_WEEK`,
#: and not by accident: this is a guillotine league, so the field starts at 18
#: teams and loses one every week. After sixteen cuts two teams are left, they
#: play week 17, and the champion is decided there -- nobody is left to play
#: week 18, the last week of the NFL regular season that ``LAST_REGULAR_WEEK``
#: names. A trade proposed after week 17 therefore has no week left to help.
#:
#: TODO(rules): this is the league's *last playable week*, not a deadline the
#: commissioner set. The rules document
#: (``docs/rules/ultimate-guillotine-gulag-league-rules.docx``) names none --
#: its "Trading Rules" section covers commissioner approval, locked players and
#: the gulag freeze, and no week -- and nothing in the data layer caches one:
#: ``public.seasons`` carries the scoring settings, the roster positions and the
#: waiver budget, and no deadline column. If a real deadline is ever set, it
#: belongs on ``public.seasons`` beside ``waiver_budget``, read off the
#: snapshot, and this constant becomes the fallback for a season row that
#: predates the column.
TRADE_DEADLINE_WEEK = 17

__all__ = ["TRADE_DEADLINE_WEEK", "DeadlinePassed", "Rejected", "deadline_passed", "verify"]


class Rejected(Exception):
    """Raised when a response says something the candidate set does not support.

    ``reason`` is written for the ops log, not for the chat: it names ids,
    amounts and members freely, and the league only ever sees the one fixed
    fallback line.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DeadlinePassed(Rejected):
    """The snapshot's week is past :data:`TRADE_DEADLINE_WEEK`.

    Distinct from every other rejection because the league should hear a
    different sentence: a fabricated answer earns "try again in a few minutes",
    which is true -- a second call may well come back sound -- while a passed
    deadline earns
    :func:`~ultimate_guillotine.advisor.format.format_deadline_passed`, because
    no number of retries will move the week. Catch it *before*
    :class:`Rejected`.

    It is nonetheless a subclass, so the two failure modes are the ones worth
    having: a caller that catches it first says the right thing, and a caller
    that only catches :class:`Rejected` says the wrong thing rather than
    crashing with an unhandled exception in front of the league. The path that
    costs nothing is :func:`deadline_passed`, checked before the model call.
    """


def deadline_passed(snapshot: LeagueSnapshot) -> bool:
    """True when this snapshot's week is past :data:`TRADE_DEADLINE_WEEK`.

    The pre-flight check: Task 9 calls it before building a prompt, so a request
    after the deadline is answered from the snapshot alone and no model call is
    paid for. :func:`verify` asks the same question on the way back out.
    """
    return snapshot.week > TRADE_DEADLINE_WEEK


class _Facts(NamedTuple):
    """The snapshot reduced, once per response, to the two lookups every check needs.

    Both were rebuilt per leg before: :meth:`LeagueSnapshot.player_names` walks
    every holding on every roster, and resolving a member walks every team. A
    three-proposal answer asks each of those a dozen times over a snapshot that
    cannot change while it is being verified, so they are built once here and
    passed down.
    """

    #: Sleeper player id to the name the league renders, for every rostered player.
    players: Mapping[str, str]
    #: Every name a member answers to, casefolded, to the team
    #: :meth:`LeagueSnapshot.team_by_name` resolves it to -- ``None`` included,
    #: which is what it answers for a name two members share.
    members: Mapping[str, AdvisorTeamState | None]

    def team(self, name: str) -> AdvisorTeamState:
        """The team a name refers to, or the reason it refers to nobody tradable."""
        team = self.members.get(name.casefold())
        if team is None:
            raise Rejected(f"unknown member in the proposal: {name}")
        if team.is_eliminated:
            raise Rejected(f"{team.member_label} is eliminated and may not be traded with")
        return team


def _facts(snapshot: LeagueSnapshot) -> _Facts:
    """Both lookups, built once.

    The member index is built *by asking* :meth:`LeagueSnapshot.team_by_name`
    for each name rather than by re-deriving the match, so the rule about a name
    two members share stays owned by the one method that states it and cannot be
    quietly re-implemented differently here.
    """
    names = {name for team in snapshot.teams for name in (team.member_label, team.display_name)}
    return _Facts(
        players=snapshot.player_names(),
        members={name.casefold(): snapshot.team_by_name(name) for name in names},
    )


def _resolved(facts: _Facts, proposal: AdvisedTrade) -> AdvisedTrade:
    """Every member the proposal names, replaced by the label the league renders.

    Members arrive checked *and* canonicalized in one pass: the snapshot matches
    either the rendered label or the join key, and only the label leaves here,
    so a model that answered with ``members.display_name`` cannot get the join
    key printed into the chat.
    """
    return proposal.model_copy(
        update={
            "counterparties": [facts.team(name).member_label for name in proposal.counterparties],
            "asker_receives": [_resolved_leg(facts, leg) for leg in proposal.asker_receives],
            "asker_sends": [_resolved_leg(facts, leg) for leg in proposal.asker_sends],
        }
    )


def _resolved_leg(facts: _Facts, leg: OfferLeg) -> OfferLeg:
    return leg.model_copy(
        update={
            "from_member": facts.team(leg.from_member).member_label,
            "to_member": facts.team(leg.to_member).member_label,
        }
    )


def _key(leg: OfferLeg | CandidateLeg) -> tuple[str, str | None, int | None, str, str]:
    """What makes two legs the same leg. Deliberately not the player's name."""
    return (leg.kind, leg.player_id, leg.amount, leg.from_member, leg.to_member)


def _checked_side(
    facts: _Facts,
    advised: Sequence[OfferLeg],
    offered: Sequence[CandidateLeg],
    index: int,
) -> list[OfferLeg]:
    """One direction of one proposal, leg by leg and then as a whole."""
    expected = Counter(_key(leg) for leg in offered)
    legs: list[OfferLeg] = []
    for leg in advised:
        if leg.kind == "player":
            if leg.player_id not in facts.players:
                raise Rejected(f"player not on any roster in this snapshot: {leg.player_id}")
        elif leg.amount is None or leg.amount > facts.team(leg.from_member).faab_remaining:
            raise Rejected(f"FAAB above {leg.from_member}'s remaining budget: {leg.amount}")
        if _key(leg) not in expected:
            raise Rejected(f"a leg's amount or direction is not candidate {index}'s")
        legs.append(
            leg
            if leg.player_id is None
            else leg.model_copy(update={"player_name": facts.players[leg.player_id]})
        )
    if Counter(_key(leg) for leg in advised) != expected:
        raise Rejected(f"the proposal's legs are not candidate {index}'s legs")
    return legs


def _checked(
    facts: _Facts, proposal: AdvisedTrade, candidate: Candidate, index: int
) -> AdvisedTrade:
    """One proposal against the one candidate its index points at."""
    if set(proposal.counterparties) != {candidate.counterparty}:
        raise Rejected(
            f"counterparty {', '.join(proposal.counterparties)} is not candidate "
            f"{index}'s counterparty {candidate.counterparty}"
        )
    if proposal.structure != candidate.structure:
        raise Rejected(
            f"structure {proposal.structure} is not candidate {index}'s {candidate.structure}"
        )
    if candidate.structure == "rental" and not proposal.return_condition:
        raise Rejected(f"candidate {index} is a rental with no return condition in the answer")
    code = proposal.comparable_trade_code
    if code is not None and (
        not TRADE_CODE.fullmatch(code) or code != candidate.comparable_trade_code
    ):
        raise Rejected(f"comparable trade code is not candidate {index}'s: {code}")
    return proposal.model_copy(
        update={
            "asker_receives": _checked_side(
                facts, proposal.asker_receives, candidate.asker_receives, index
            ),
            "asker_sends": _checked_side(facts, proposal.asker_sends, candidate.asker_sends, index),
            "return_condition": candidate.return_condition or proposal.return_condition,
        }
    )


def verify(
    response: TradeAdviceResponse,
    candidates: Sequence[Candidate],
    snapshot: LeagueSnapshot,
    asker_member_id: int,
) -> TradeAdviceResponse:
    """Return a corrected copy of ``response``, or raise :class:`Rejected`."""
    asker = snapshot.team_for_member(asker_member_id)
    if asker is None:
        raise Rejected(f"the asker, member {asker_member_id}, has no team in this snapshot")
    if asker.is_eliminated:
        raise Rejected(f"the asker, {asker.member_label}, is eliminated")
    if deadline_passed(snapshot):
        # Before the status checks: past the deadline there is nothing to say
        # about any answer, sound or not, beyond that it is too late.
        raise DeadlinePassed(
            f"week {snapshot.week} is past the trade deadline, week {TRADE_DEADLINE_WEEK}"
        )
    if response.status != "ok":
        if response.proposals:
            raise Rejected(f"status {response.status} still carries a proposal")
        # Nothing left to check: an honest refusal names no player and no price.
        return response
    if not response.proposals:
        raise Rejected("status ok with no proposal in it")

    facts = _facts(snapshot)
    checked: list[AdvisedTrade] = []
    seen: set[int] = set()
    for raw in response.proposals:
        proposal = _resolved(facts, raw)
        index = proposal.candidate_index
        if index > len(candidates):
            raise Rejected(f"candidate {index} was never offered; there were {len(candidates)}")
        if index in seen:
            raise Rejected(f"candidate {index} is proposed twice")
        seen.add(index)
        checked.append(_checked(facts, proposal, candidates[index - 1], index))

    return response.model_copy(update={"proposals": sorted(checked, key=lambda p: p.rank)})
