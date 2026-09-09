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

**Two things are repaired rather than rejected**: a player's display name and a
rental's return condition. In both cases the fact lives on the candidate -- the
id and the return week -- and the words are decoration the model may respell,
so correcting the decoration beats refusing a sound proposal. Dropping the
return condition entirely is not a respelling, and is rejected.
"""

from collections import Counter
from collections.abc import Sequence

from ultimate_guillotine.advisor.candidates import Candidate, CandidateLeg
from ultimate_guillotine.advisor.models import AdvisedTrade, OfferLeg, TradeAdviceResponse
from ultimate_guillotine.advisor.state import AdvisorTeamState, LeagueSnapshot
from ultimate_guillotine.trades.registrar import TRADE_CODE

#: The last week a trade may be proposed in.
#:
#: TODO(rules): the league's rules document
#: (``docs/rules/ultimate-guillotine-gulag-league-rules.docx``) sets no trade
#: deadline -- its "Trading Rules" section names commissioner approval, locked
#: players and the gulag freeze, and no week -- and nothing in the data layer
#: caches one: ``public.seasons`` carries the scoring settings, the roster
#: positions and the waiver budget, and no deadline column. The number here is
#: therefore the last week the league plays: the rules' own season table cuts
#: the field to one champion in week 17, so a trade proposed after it has no
#: week left to help. If a deadline is ever written down, it belongs on
#: ``public.seasons`` beside ``waiver_budget``, read off the snapshot, and this
#: constant becomes the fallback for a season row that predates the column.
TRADE_DEADLINE_WEEK = 17

__all__ = ["TRADE_DEADLINE_WEEK", "Rejected", "verify"]


class Rejected(Exception):
    """Raised when a response says something the candidate set does not support.

    ``reason`` is written for the ops log, not for the chat: it names ids,
    amounts and members freely, and the league only ever sees the one fixed
    fallback line.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _team(snapshot: LeagueSnapshot, name: str) -> AdvisorTeamState:
    """The team a name refers to, or the reason it refers to nobody tradable."""
    team = snapshot.team_by_name(name)
    if team is None:
        raise Rejected(f"unknown member in the proposal: {name}")
    if team.is_eliminated:
        raise Rejected(f"{team.member_label} is eliminated and may not be traded with")
    return team


def _resolved(snapshot: LeagueSnapshot, proposal: AdvisedTrade) -> AdvisedTrade:
    """Every member the proposal names, replaced by the label the league renders.

    Members arrive checked *and* canonicalized in one pass: the snapshot matches
    either the rendered label or the join key, and only the label leaves here,
    so a model that answered with ``members.display_name`` cannot get the join
    key printed into the chat.
    """
    return proposal.model_copy(
        update={
            "counterparties": [_team(snapshot, name).member_label
                               for name in proposal.counterparties],
            "asker_receives": [_resolved_leg(snapshot, leg) for leg in proposal.asker_receives],
            "asker_sends": [_resolved_leg(snapshot, leg) for leg in proposal.asker_sends],
        }
    )


def _resolved_leg(snapshot: LeagueSnapshot, leg: OfferLeg) -> OfferLeg:
    return leg.model_copy(
        update={
            "from_member": _team(snapshot, leg.from_member).member_label,
            "to_member": _team(snapshot, leg.to_member).member_label,
        }
    )


def _key(leg: OfferLeg | CandidateLeg) -> tuple[str, str | None, int | None, str, str]:
    """What makes two legs the same leg. Deliberately not the player's name."""
    return (leg.kind, leg.player_id, leg.amount, leg.from_member, leg.to_member)


def _checked_side(
    snapshot: LeagueSnapshot,
    advised: Sequence[OfferLeg],
    offered: Sequence[CandidateLeg],
    index: int,
) -> list[OfferLeg]:
    """One direction of one proposal, leg by leg and then as a whole."""
    names = snapshot.player_names()
    expected = Counter(_key(leg) for leg in offered)
    legs: list[OfferLeg] = []
    for leg in advised:
        if leg.kind == "player":
            if leg.player_id not in names:
                raise Rejected(f"player not on any roster in this snapshot: {leg.player_id}")
        elif leg.amount is None or leg.amount > _team(snapshot, leg.from_member).faab_remaining:
            raise Rejected(f"FAAB above {leg.from_member}'s remaining budget: {leg.amount}")
        if _key(leg) not in expected:
            raise Rejected(f"a leg's amount or direction is not candidate {index}'s")
        legs.append(
            leg if leg.player_id is None
            else leg.model_copy(update={"player_name": names[leg.player_id]})
        )
    if Counter(_key(leg) for leg in advised) != expected:
        raise Rejected(f"the proposal's legs are not candidate {index}'s legs")
    return legs


def _checked(
    snapshot: LeagueSnapshot, proposal: AdvisedTrade, candidate: Candidate, index: int
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
                snapshot, proposal.asker_receives, candidate.asker_receives, index
            ),
            "asker_sends": _checked_side(
                snapshot, proposal.asker_sends, candidate.asker_sends, index
            ),
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
    if response.status != "ok":
        if response.proposals:
            raise Rejected(f"status {response.status} still carries a proposal")
        # Nothing left to check: an honest refusal names no player and no price.
        return response
    if not response.proposals:
        raise Rejected("status ok with no proposal in it")
    if snapshot.week > TRADE_DEADLINE_WEEK:
        raise Rejected(f"week {snapshot.week} is past the trade deadline")

    checked: list[AdvisedTrade] = []
    seen: set[int] = set()
    for raw in response.proposals:
        proposal = _resolved(snapshot, raw)
        index = proposal.candidate_index
        if index > len(candidates):
            raise Rejected(f"candidate {index} was never offered; there were {len(candidates)}")
        if index in seen:
            raise Rejected(f"candidate {index} is proposed twice")
        seen.add(index)
        checked.append(_checked(snapshot, proposal, candidates[index - 1], index))

    return response.model_copy(update={"proposals": sorted(checked, key=lambda p: p.rank)})
