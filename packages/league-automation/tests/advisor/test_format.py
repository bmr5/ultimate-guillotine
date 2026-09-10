"""The chat text the league actually reads."""

from dataclasses import replace
from decimal import Decimal

from tests.advisor.fixture import advised_response, fixture_snapshot
from ultimate_guillotine.advisor import prompt
from ultimate_guillotine.advisor.candidates import generate_candidates
from ultimate_guillotine.advisor.detect import Ask
from ultimate_guillotine.advisor.format import (
    DEADLINE_PASSED,
    FALLBACK,
    NO_PROJECTIONS,
    NOT_COMPUTED,
    SOURCE_PREFIX,
    format_advice,
    format_deadline_passed,
    format_refusal,
    format_rejected,
    format_stale,
    format_unknown_asker,
)
from ultimate_guillotine.advisor.models import AdvisedTrade, OfferLeg, TradeAdviceResponse
from ultimate_guillotine.advisor.scoring import score_league
from ultimate_guillotine.core.signature import BOT_SIGNATURE

ASK = Ask(("RB",), "acquire", None, False, (), False)
#: The whole rendered message for the two best RB candidates in the fixture
#: league, week 6. Written out rather than assembled from the same helpers the
#: renderer uses, so that a change to the layout has to be typed here too --
#: which is the point: this is the text an eighteen-person group chat reads.
GOLDEN = """RB rental, next 2 weeks — 2 ideas
1) Member02: you send 128 FAAB, you get Bench 02-0
   Your lineup, Week 6: +4.60
   Why: They are deep at RB and you are thin (1).
   Risk: His RB has a Week 12 bye (1).
2) Member01: you send 128 FAAB, you get Bench 01-0
   Your lineup, Week 6: +4.00
   Why: They are deep at RB and you are thin (2).
   Risk: His RB has a Week 12 bye (2).
Source: registered trades + Week 6 projections"""
RENTAL_ASK = Ask(("RB",), "acquire", 3, True, (), False)
ASKER = 18


def _candidates(ask: Ask = ASK, **kwargs):
    snapshot = fixture_snapshot(**kwargs)
    candidates = generate_candidates(snapshot, score_league(snapshot), ASKER, ask, [])
    assert candidates, "the fixture must offer something to render"
    return snapshot, candidates


def _response(status="ok", note=None, proposals=None) -> TradeAdviceResponse:
    return TradeAdviceResponse(
        status=status,
        headline="RB rental, next 2 weeks",
        note=note,
        proposals=proposals
        if proposals is not None
        else [
            AdvisedTrade(
                candidate_index=1,
                rank=1,
                counterparties=["Member03"],
                structure="rental",
                return_condition="returns before the Week 10 lock",
                reasoning="Member03 is deepest at RB and you are thinnest.",
                risk="His bye is Week 12, right when the rental ends.",
                comparable_trade_code="T-2026-001",
                asker_receives=[
                    OfferLeg(
                        kind="player",
                        player_id="p03b0",
                        player_name="Bench 03-0",
                        amount=None,
                        from_member="Member03",
                        to_member="Member18",
                    )
                ],
                asker_sends=[
                    OfferLeg(
                        kind="faab",
                        player_id=None,
                        player_name=None,
                        amount=120,
                        from_member="Member18",
                        to_member="Member03",
                    )
                ],
            )
        ],
    )


def test_advice_reads_as_a_short_numbered_list_with_a_source_line() -> None:
    text = format_advice(_response(), fixture_snapshot(), projections_known=True, candidates=())
    lines = text.splitlines()
    assert lines[0] == "RB rental, next 2 weeks — 1 idea"
    assert lines[1].startswith("1) Member03: you send 120 FAAB, you get Bench 03-0")
    assert "returns before the Week 10 lock" in lines[1]
    assert lines[2].strip().startswith("Your lineup")
    assert lines[3].strip().startswith("Why: ")
    assert lines[4].strip().startswith("Risk: ")
    assert lines[-1].startswith(SOURCE_PREFIX)
    assert BOT_SIGNATURE not in text


def test_a_proposal_with_no_candidate_still_gets_a_lineup_line() -> None:
    """A missing figure is said out loud; a missing line reads as "no change"."""
    text = format_advice(_response(), fixture_snapshot(), projections_known=True, candidates=())
    lineup = [line for line in text.splitlines() if line.strip().startswith("Your lineup")]
    assert lineup == [f"   Your lineup: {NOT_COMPUTED}"]


def test_the_text_is_plain_and_never_more_than_three_ideas() -> None:
    snapshot, candidates = _candidates()
    proposals = [
        advised_response(candidate, index=index).proposals[0].model_copy(update={"rank": index})
        for index, candidate in enumerate(candidates[:3], start=1)
    ]
    text = format_advice(
        _response(proposals=proposals), snapshot, projections_known=True, candidates=candidates
    )
    assert text.startswith("RB rental, next 2 weeks — 3 ideas")
    assert "3)" in text and "4)" not in text
    for markup in ("**", "##", "- [", "`"):
        assert markup not in text


def test_the_source_line_names_the_week_and_the_price_history() -> None:
    text = format_advice(_response(), fixture_snapshot(), projections_known=True, candidates=())
    assert "Week 6 projections" in text and "registered trades" in text


def test_without_projections_the_source_line_says_so_and_no_number_appears() -> None:
    text = format_advice(_response(), fixture_snapshot(), projections_known=False, candidates=())
    assert "projections unavailable" in text
    assert "Week 6 projections" not in text


def test_a_known_lineup_change_is_rendered_with_the_weeks_it_covers() -> None:
    snapshot, candidates = _candidates()
    response = advised_response(candidates[0])
    text = format_advice(response, snapshot, projections_known=True, candidates=candidates)
    assert f"Week {snapshot.week}: {candidates[0].asker_delta:+.2f}" in text


def test_a_rental_names_the_whole_span_its_number_covers() -> None:
    snapshot, candidates = _candidates(RENTAL_ASK, horizon_weeks=3)
    response = advised_response(candidates[0])
    text = format_advice(response, snapshot, projections_known=True, candidates=candidates)
    assert "Weeks 6–8" in text


def test_an_unknown_lineup_change_says_so_rather_than_showing_a_zero() -> None:
    snapshot, candidates = _candidates(coverage_pct=Decimal("10.00"))
    assert candidates[0].asker_delta is None
    response = advised_response(candidates[0])
    text = format_advice(response, snapshot, projections_known=False, candidates=candidates)
    assert NOT_COMPUTED in text
    assert "0.00" not in text


def test_the_chat_text_never_names_a_join_key_or_a_pressure_rank() -> None:
    snapshot, _ = _candidates()
    teams = tuple(
        replace(team, member_label="Deuce") if team.member_id == 2 else team
        for team in snapshot.teams
    )
    snapshot = replace(snapshot, teams=teams)
    candidates = generate_candidates(snapshot, score_league(snapshot), ASKER, ASK, [])
    candidate = next(c for c in candidates if c.counterparty == "Deuce")
    index = candidates.index(candidate) + 1
    response = advised_response(candidate, index=index)
    text = format_advice(response, snapshot, projections_known=True, candidates=candidates)
    assert "Deuce" in text
    assert "Member02" not in text
    assert "pressure" not in text.lower()


def test_no_good_trades_sends_one_honest_line() -> None:
    text = format_advice(
        _response(
            status="no_good_trades",
            note="Nothing on the board beats your RB2.",
            proposals=[],
        ),
        fixture_snapshot(),
        projections_known=True,
        candidates=(),
    )
    assert "Nothing on the board beats your RB2." in text
    assert "1)" not in text


def test_insufficient_data_names_the_missing_record() -> None:
    text = format_advice(
        _response(status="insufficient_data", note="No FAAB balances have synced.", proposals=[]),
        fixture_snapshot(),
        projections_known=True,
        candidates=(),
    )
    assert "No FAAB balances have synced." in text


def test_the_chat_says_an_unknown_figure_the_way_the_facts_block_does() -> None:
    """Two modules, one vocabulary -- the drift guard format.py's comment names."""
    assert NOT_COMPUTED == prompt.NOT_COMPUTED
    assert NO_PROJECTIONS == prompt.NO_PROJECTIONS


def test_the_fixed_replies_are_short_and_unsigned() -> None:
    fixed = (
        format_unknown_asker(),
        format_stale(47),
        format_refusal(),
        format_rejected(),
        format_deadline_passed(),
    )
    for text in fixed:
        assert BOT_SIGNATURE not in text
        assert len(text.splitlines()) <= 2
    assert "47" in format_stale(47)


def test_the_fallback_after_a_rejection_is_one_fixed_line() -> None:
    assert format_rejected() == FALLBACK
    assert FALLBACK == "I can't put advice together yet, kitten — try again in a few minutes."


def test_a_passed_deadline_says_so_instead_of_asking_for_a_retry() -> None:
    """The deadline is not a transient failure, so it does not borrow that line."""
    assert format_deadline_passed() == DEADLINE_PASSED
    assert DEADLINE_PASSED == "The trade deadline has passed, kitten, so I can't suggest trades."
    assert format_deadline_passed() != FALLBACK


def test_two_proposals_render_exactly_this_message() -> None:
    """The whole message, character for character -- the layout nobody may drift."""
    snapshot, candidates = _candidates()
    proposals = [
        advised_response(candidate, index=index)
        .proposals[0]
        .model_copy(
            update={
                "rank": index,
                "reasoning": f"They are deep at RB and you are thin ({index}).",
                "risk": f"His RB has a Week 12 bye ({index}).",
            }
        )
        for index, candidate in enumerate(candidates[:2], start=1)
    ]
    text = format_advice(
        _response(proposals=proposals), snapshot, projections_known=True, candidates=candidates
    )
    assert text == GOLDEN
