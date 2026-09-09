"""The fixture league, plus the one helper only a test has any use for.

The league itself moved into :mod:`ultimate_guillotine.advisor.fixture` when
``ug advisor ask --fixture`` and the golden request set both needed to build it
outside the test suite. It is re-exported here so every existing test keeps the
one import it already had, and so there is still a single place a test reaches
for "the league".

:func:`advised_response` stays here: it fabricates a model answer in order to
tamper with it, which is a thing only a test does.
"""

from ultimate_guillotine.advisor.candidates import Candidate, CandidateLeg
from ultimate_guillotine.advisor.fixture import (
    ASKER_MEMBER_ID,
    BENCH,
    ELIMINATED_MEMBER_ID,
    FIXTURE_SEASON,
    FIXTURE_SEASON_ID,
    FIXTURE_SYNCED_AT,
    LINEUP,
    NEAR_CUT_MEMBER_ID,
    ROTATION,
    fixture_snapshot,
)
from ultimate_guillotine.advisor.models import AdvisedTrade, OfferLeg, TradeAdviceResponse

__all__ = [
    "ASKER_MEMBER_ID",
    "BENCH",
    "ELIMINATED_MEMBER_ID",
    "FIXTURE_SEASON",
    "FIXTURE_SEASON_ID",
    "FIXTURE_SYNCED_AT",
    "LINEUP",
    "NEAR_CUT_MEMBER_ID",
    "ROTATION",
    "advised_response",
    "fixture_snapshot",
    "offer_leg",
]


def offer_leg(leg: CandidateLeg) -> OfferLeg:
    """One candidate leg as the model would have answered it back."""
    return OfferLeg(
        kind=leg.kind,
        player_id=leg.player_id,
        player_name=leg.player_name,
        amount=leg.amount,
        from_member=leg.from_member,
        to_member=leg.to_member,
    )


def advised_response(
    candidate: Candidate,
    *,
    index: int = 1,
    rank: int = 1,
    status: str = "ok",
    headline: str = "RB help",
    note: str | None = None,
    **overrides: object,
) -> TradeAdviceResponse:
    """A faithful answer to one candidate, which a test then tampers with.

    Every test in :mod:`tests.advisor.test_verify` starts from a response the
    verifier must accept and changes exactly one thing, so a failure names the
    one field that broke rather than the whole shape of the answer.
    """
    proposal = AdvisedTrade(
        candidate_index=index,
        rank=rank,
        counterparties=[candidate.counterparty],
        structure=candidate.structure,
        return_condition=candidate.return_condition,
        reasoning="They are deep at RB and you are thin.",
        risk="His RB has a Week 12 bye.",
        comparable_trade_code=candidate.comparable_trade_code,
        asker_receives=[offer_leg(leg) for leg in candidate.asker_receives],
        asker_sends=[offer_leg(leg) for leg in candidate.asker_sends],
    )
    return TradeAdviceResponse(
        status=status,
        headline=headline,
        note=note,
        proposals=[proposal.model_copy(update=overrides)],
    )
