"""The deterministic check that stands between the model's answer and the chat."""

from dataclasses import replace

import pytest

from tests.advisor.fixture import advised_response, fixture_snapshot
from ultimate_guillotine.advisor.candidates import generate_candidates
from ultimate_guillotine.advisor.detect import Ask
from ultimate_guillotine.advisor.models import AdvisedTrade, TradeAdviceResponse
from ultimate_guillotine.advisor.scoring import score_league
from ultimate_guillotine.advisor.verify import (
    TRADE_DEADLINE_WEEK,
    DeadlinePassed,
    Rejected,
    deadline_passed,
    verify,
)

ASK = Ask(("RB",), "acquire", None, False, (), False)
RENTAL_ASK = Ask(("RB",), "acquire", 3, True, (), False)
ASKER = 18


def _setup(ask: Ask = ASK, **kwargs):
    snapshot = fixture_snapshot(**kwargs)
    candidates = generate_candidates(snapshot, score_league(snapshot), ASKER, ask, [])
    assert candidates, "the fixture must offer something to verify against"
    return snapshot, candidates


def _tamper(response: TradeAdviceResponse, **fields) -> TradeAdviceResponse:
    """Change one thing about the single proposal, leaving the rest faithful."""
    return response.model_copy(
        update={"proposals": [response.proposals[0].model_copy(update=fields)]}
    )


def test_a_faithful_response_passes_and_canonicalizes_player_names() -> None:
    snapshot, candidates = _setup()
    response = advised_response(candidates[0])
    wrong_name = response.proposals[0].asker_receives[0].model_copy(
        update={"player_name": "Somebody Else"}
    )
    tampered = _tamper(response, asker_receives=[wrong_name])
    verified = verify(tampered, candidates, snapshot, ASKER)
    assert verified.proposals[0].asker_receives[0].player_name == (
        candidates[0].asker_receives[0].player_name
    )


def test_an_invented_player_is_rejected() -> None:
    snapshot, candidates = _setup()
    response = advised_response(candidates[0])
    fake = response.proposals[0].asker_receives[0].model_copy(update={"player_id": "not-a-real-id"})
    with pytest.raises(Rejected, match="player"):
        verify(_tamper(response, asker_receives=[fake]), candidates, snapshot, ASKER)


def test_an_unknown_member_is_rejected() -> None:
    snapshot, candidates = _setup()
    response = advised_response(candidates[0], counterparties=["Nobody"])
    with pytest.raises(Rejected, match="member"):
        verify(response, candidates, snapshot, ASKER)


def test_a_member_is_checked_before_the_candidate_it_claims_to_be() -> None:
    """The unknown name is the reason, even when the index is nonsense too."""
    snapshot, candidates = _setup()
    response = advised_response(candidates[0], counterparties=["Nobody"], candidate_index=99)
    with pytest.raises(Rejected, match="member"):
        verify(response, candidates, snapshot, ASKER)


def test_a_name_two_members_share_is_rejected_rather_than_guessed_at() -> None:
    """The hoisted member index answers exactly what ``team_by_name`` answers."""
    snapshot, _ = _setup()
    teams = tuple(
        replace(team, member_label="Twin") if team.member_id in (2, 3) else team
        for team in snapshot.teams
    )
    snapshot = replace(snapshot, teams=teams)
    candidates = generate_candidates(snapshot, score_league(snapshot), ASKER, ASK, [])
    candidate = next(c for c in candidates if c.counterparty == "Twin")
    index = candidates.index(candidate) + 1
    assert snapshot.team_by_name("Twin") is None
    with pytest.raises(Rejected, match="unknown member"):
        verify(advised_response(candidate, index=index), candidates, snapshot, ASKER)


def test_a_trade_with_an_eliminated_team_is_rejected() -> None:
    snapshot, candidates = _setup()
    response = advised_response(candidates[0], counterparties=["Member17"])
    with pytest.raises(Rejected, match="eliminated"):
        verify(response, candidates, snapshot, ASKER)


def test_faab_above_the_senders_budget_is_rejected() -> None:
    snapshot, candidates = _setup()
    response = advised_response(candidates[0])
    huge = response.proposals[0].asker_sends[0].model_copy(update={"amount": 99999})
    with pytest.raises(Rejected, match="FAAB"):
        verify(_tamper(response, asker_sends=[huge]), candidates, snapshot, ASKER)


def test_an_amount_that_does_not_match_the_candidate_is_rejected() -> None:
    snapshot, candidates = _setup()
    response = advised_response(candidates[0])
    changed = response.proposals[0].asker_sends[0].model_copy(update={"amount": 7})
    with pytest.raises(Rejected, match="amount"):
        verify(_tamper(response, asker_sends=[changed]), candidates, snapshot, ASKER)


def test_a_dropped_faab_leg_is_rejected() -> None:
    """Half a trade is not a cheaper trade -- it is a different one."""
    snapshot, candidates = _setup()
    response = advised_response(candidates[0])
    with pytest.raises(Rejected, match="legs"):
        verify(_tamper(response, asker_sends=[]), candidates, snapshot, ASKER)


def test_a_repeated_leg_is_rejected() -> None:
    snapshot, candidates = _setup()
    response = advised_response(candidates[0])
    leg = response.proposals[0].asker_receives[0]
    with pytest.raises(Rejected, match="legs"):
        verify(_tamper(response, asker_receives=[leg, leg]), candidates, snapshot, ASKER)


def test_a_leg_from_another_candidate_is_rejected() -> None:
    snapshot, candidates = _setup()
    response = advised_response(candidates[0])
    other = advised_response(candidates[1], index=2).proposals[0].asker_receives[0]
    tampered = _tamper(response, asker_receives=[response.proposals[0].asker_receives[0], other])
    with pytest.raises(Rejected, match="candidate"):
        verify(tampered, candidates, snapshot, ASKER)


def test_a_candidate_index_nobody_handed_out_is_rejected() -> None:
    snapshot, candidates = _setup()
    response = advised_response(candidates[0], candidate_index=len(candidates) + 1)
    with pytest.raises(Rejected, match="candidate"):
        verify(response, candidates, snapshot, ASKER)


def test_a_counterparty_that_is_not_the_candidates_is_rejected() -> None:
    snapshot, candidates = _setup()
    response = advised_response(candidates[0], counterparties=[candidates[1].counterparty])
    with pytest.raises(Rejected, match="counterparty"):
        verify(response, candidates, snapshot, ASKER)


def test_the_same_candidate_cannot_be_proposed_twice() -> None:
    snapshot, candidates = _setup()
    first = advised_response(candidates[0]).proposals[0]
    response = TradeAdviceResponse(
        status="ok",
        headline="RB help",
        note=None,
        proposals=[first, first.model_copy(update={"rank": 2})],
    )
    with pytest.raises(Rejected, match="twice"):
        verify(response, candidates, snapshot, ASKER)


def test_a_structure_the_candidate_does_not_have_is_rejected() -> None:
    snapshot, candidates = _setup(RENTAL_ASK)
    response = advised_response(candidates[0], structure="permanent")
    with pytest.raises(Rejected, match="structure"):
        verify(response, candidates, snapshot, ASKER)


def test_a_rental_without_a_return_condition_is_rejected() -> None:
    """Unreachable through the schema, and still checked: two locks, one door."""
    snapshot, candidates = _setup(RENTAL_ASK)
    response = advised_response(candidates[0])
    with pytest.raises(Rejected, match="return condition"):
        verify(_tamper(response, return_condition=None), candidates, snapshot, ASKER)


def test_a_reworded_return_condition_is_restored_to_the_candidates() -> None:
    snapshot, candidates = _setup(RENTAL_ASK)
    response = advised_response(candidates[0], return_condition="whenever, honestly")
    verified = verify(response, candidates, snapshot, ASKER)
    assert verified.proposals[0].return_condition == candidates[0].return_condition


def test_a_comparable_code_not_in_the_candidate_set_is_rejected() -> None:
    snapshot, candidates = _setup()
    response = advised_response(candidates[0], comparable_trade_code="T-1999-001")
    with pytest.raises(Rejected, match="comparable"):
        verify(response, candidates, snapshot, ASKER)


def test_the_deadline_is_known_before_the_model_is_called() -> None:
    """The pre-flight check Task 9 uses, so a late ask costs nothing to answer."""
    assert deadline_passed(fixture_snapshot(week=TRADE_DEADLINE_WEEK)) is False
    assert deadline_passed(fixture_snapshot(week=TRADE_DEADLINE_WEEK + 1)) is True


def test_a_proposal_after_the_trade_deadline_is_its_own_outcome() -> None:
    """Not the generic rejection: the league hears the deadline, not "try again"."""
    snapshot, candidates = _setup(week=TRADE_DEADLINE_WEEK + 1)
    response = advised_response(candidates[0])
    with pytest.raises(DeadlinePassed, match="deadline"):
        verify(response, candidates, snapshot, ASKER)


def test_the_deadline_outcome_is_still_a_rejection() -> None:
    """A caller that only catches Rejected sends the wrong line, not a traceback."""
    assert issubclass(DeadlinePassed, Rejected)
    snapshot, candidates = _setup(week=TRADE_DEADLINE_WEEK + 1)
    with pytest.raises(Rejected) as caught:
        verify(advised_response(candidates[0]), candidates, snapshot, ASKER)
    assert str(TRADE_DEADLINE_WEEK) in caught.value.reason


def test_a_refusal_after_the_deadline_is_the_deadline_too() -> None:
    """The week is a fact about the league, not about how the model answered."""
    snapshot, candidates = _setup(week=TRADE_DEADLINE_WEEK + 1)
    response = TradeAdviceResponse(
        status="no_good_trades", headline="Nothing doing", proposals=[], note="Stand pat."
    )
    with pytest.raises(DeadlinePassed):
        verify(response, candidates, snapshot, ASKER)


def test_no_good_trades_with_no_proposals_passes_untouched() -> None:
    snapshot, candidates = _setup()
    response = TradeAdviceResponse(
        status="no_good_trades",
        headline="Nothing beats standing pat",
        proposals=[],
        note="Your RB2 already outprojects every spare on the board.",
    )
    assert verify(response, candidates, snapshot, ASKER) == response


def test_ok_with_no_proposals_is_rejected() -> None:
    snapshot, candidates = _setup()
    response = TradeAdviceResponse(status="ok", headline="x", proposals=[], note=None)
    with pytest.raises(Rejected, match="proposal"):
        verify(response, candidates, snapshot, ASKER)


def test_a_refusal_that_still_carries_a_proposal_is_rejected() -> None:
    snapshot, candidates = _setup()
    response = advised_response(candidates[0], status="no_good_trades")
    with pytest.raises(Rejected, match="proposal"):
        verify(response, candidates, snapshot, ASKER)


def test_an_unknown_asker_is_rejected() -> None:
    snapshot, candidates = _setup()
    response = advised_response(candidates[0])
    with pytest.raises(Rejected, match="asker"):
        verify(response, candidates, snapshot, 999)


def test_the_counterparty_comes_back_as_the_label_the_league_renders() -> None:
    """A model that answered with the join key must not get it printed."""
    snapshot, _ = _setup()
    teams = tuple(
        replace(team, member_label="Deuce") if team.member_id == 2 else team
        for team in snapshot.teams
    )
    snapshot = replace(snapshot, teams=teams)
    candidates = generate_candidates(snapshot, score_league(snapshot), ASKER, ASK, [])
    candidate = next(c for c in candidates if c.counterparty == "Deuce")
    index = candidates.index(candidate) + 1
    response = advised_response(candidate, index=index, counterparties=["Member02"])
    verified = verify(response, candidates, snapshot, ASKER)
    assert verified.proposals[0].counterparties == ["Deuce"]


def test_proposals_come_back_in_rank_order() -> None:
    snapshot, candidates = _setup()
    second = advised_response(candidates[1], index=2).proposals[0].model_copy(
        update={"rank": 2}
    )
    first = advised_response(candidates[0]).proposals[0]
    response = TradeAdviceResponse(
        status="ok", headline="RB help", note=None, proposals=[second, first]
    )
    verified = verify(response, candidates, snapshot, ASKER)
    assert [p.rank for p in verified.proposals] == [1, 2]
    assert isinstance(verified.proposals[0], AdvisedTrade)
