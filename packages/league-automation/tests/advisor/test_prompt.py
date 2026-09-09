"""The schema, the versioned prompt, and the one model call the Advisor makes."""

import os
from dataclasses import replace
from decimal import Decimal

import pytest

from tests.advisor.fixture import fixture_snapshot
from ultimate_guillotine.advisor.candidates import generate_candidates
from ultimate_guillotine.advisor.detect import Ask
from ultimate_guillotine.advisor.models import AdvisedTrade, OfferLeg, TradeAdviceResponse
from ultimate_guillotine.advisor.prompt import (
    ADVICE_TIMEOUT_SECONDS,
    NO_PROJECTIONS,
    NOT_COMPUTED,
    PROMPT_VERSION,
    SCHEMA_NAME,
    advise,
    advisor_client,
    build_facts,
    load_prompt,
)
from ultimate_guillotine.advisor.scoring import score_league
from ultimate_guillotine.ai.structured import AIUsage
from ultimate_guillotine.config import Settings
from ultimate_guillotine.core.hermes_cli import find_hermes_binary

ASK = Ask(("RB",), "acquire", None, False, (), False)
ASKER = 18


class FakeAI:
    def __init__(self, result):
        self.result, self.calls = result, []

    def parse(self, system, user, schema, schema_name):
        self.calls.append((system, user, schema, schema_name))
        return self.result, AIUsage("gen-1", 10, 5, "gpt-5.6-sol")


def _setup(**kwargs):
    snapshot = fixture_snapshot(**kwargs)
    scores = score_league(snapshot)
    candidates = generate_candidates(snapshot, scores, ASKER, ASK, [])
    return snapshot, scores, candidates


def _response() -> TradeAdviceResponse:
    return TradeAdviceResponse(
        status="ok",
        headline="RB help for Member18",
        note=None,
        proposals=[
            AdvisedTrade(
                candidate_index=1,
                rank=1,
                counterparties=["Member03"],
                structure="permanent",
                return_condition=None,
                reasoning="They are deep at RB.",
                risk="Their RB has a Week 12 bye.",
                comparable_trade_code=None,
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
                        amount=40,
                        from_member="Member18",
                        to_member="Member03",
                    )
                ],
            )
        ],
    )


def test_prompt_is_versioned_and_states_the_hard_rules() -> None:
    prompt = load_prompt()
    assert PROMPT_VERSION == "2026.1"
    assert prompt.splitlines()[0] == f"<!-- prompt_version: {PROMPT_VERSION} -->"
    for phrase in ("rank", "never introduce", "FAAB", "risk", "one line"):
        assert phrase.lower() in prompt.lower()


def test_prompt_forbids_adding_players_counterparties_or_prices() -> None:
    prompt = " ".join(load_prompt().split())
    assert "may not add a player, a counterparty, or a price" in prompt
    assert "`candidate_index`" in prompt
    assert NOT_COMPUTED in prompt


def test_schema_matches_the_spec_and_bounds_the_prose() -> None:
    assert SCHEMA_NAME == "TradeAdviceResponse"
    good = _response().proposals[0].model_dump()
    with pytest.raises(ValueError):
        AdvisedTrade.model_validate(good | {"counterparties": []})
    with pytest.raises(ValueError):
        AdvisedTrade.model_validate(good | {"risk": "x" * 141})
    with pytest.raises(ValueError):
        AdvisedTrade.model_validate(good | {"reasoning": "x" * 241})
    with pytest.raises(ValueError):
        AdvisedTrade.model_validate(good | {"rank": 0})
    with pytest.raises(ValueError):
        AdvisedTrade.model_validate(good | {"nonsense": 1})
    assert TradeAdviceResponse.model_fields["status"].annotation is not None


def test_schema_refers_to_a_candidate_by_its_opaque_index() -> None:
    good = _response().proposals[0].model_dump()
    assert good["candidate_index"] == 1
    with pytest.raises(ValueError):
        AdvisedTrade.model_validate(good | {"candidate_index": 0})
    with pytest.raises(ValueError):
        AdvisedTrade.model_validate({k: v for k, v in good.items() if k != "candidate_index"})


def test_response_caps_the_proposals_and_the_prose() -> None:
    body = _response().model_dump()
    with pytest.raises(ValueError):
        TradeAdviceResponse.model_validate(body | {"proposals": body["proposals"] * 4})
    with pytest.raises(ValueError):
        TradeAdviceResponse.model_validate(body | {"headline": "x" * 121})
    with pytest.raises(ValueError):
        TradeAdviceResponse.model_validate(body | {"note": "x" * 201})
    with pytest.raises(ValueError):
        TradeAdviceResponse.model_validate(body | {"status": "maybe"})


def test_facts_carry_the_candidates_and_never_private_values() -> None:
    snapshot, scores, candidates = _setup()
    assert candidates, "the fixture must produce candidates for this to test anything"
    facts = build_facts(snapshot, scores, ASKER, ASK, candidates, [])
    assert "Member18" in facts and "Week 6" in facts
    assert "CANDIDATE 1" in facts
    for forbidden in ("chat_guid", "sender_hash", "handle", "dues", "+1555", "iMessage;"):
        assert forbidden not in facts
    # Pressure is an input, never something to say out loud (open question 2).
    assert "pressure rank" in facts.lower()


def test_facts_render_every_member_by_the_label_the_league_shows() -> None:
    snapshot, _, _ = _setup()
    teams = tuple(
        replace(
            team,
            display_name=f"join-key-{team.member_id}",
            member_label=f"Nick{team.member_id}",
        )
        for team in snapshot.teams
    )
    snapshot = replace(snapshot, teams=teams)
    scores = score_league(snapshot)
    candidates = generate_candidates(snapshot, scores, ASKER, ASK, [])
    facts = build_facts(snapshot, scores, ASKER, ASK, candidates, [])
    assert "Nick18" in facts
    assert "join-key" not in facts


def test_facts_say_a_missing_delta_could_not_be_computed_and_never_zero() -> None:
    snapshot, scores, candidates = _setup()
    blind = [
        replace(
            candidate,
            asker_delta=None,
            counterparty_delta=None,
            reasons=replace(candidate.reasons, delta_basis="incomplete"),
        )
        for candidate in candidates
    ]
    facts = build_facts(snapshot, scores, ASKER, ASK, blind, [])
    assert f"asker point change: {NOT_COMPUTED}" in facts
    assert f"counterparty point change: {NOT_COMPUTED}" in facts
    assert "point change: +0.00" not in facts and "point change: 0" not in facts


def test_advise_makes_exactly_one_call_with_the_versioned_prompt() -> None:
    snapshot, scores, candidates = _setup()
    ai = FakeAI(_response())
    result, usage = advise(ai, snapshot, scores, ASKER, ASK, candidates, [])
    assert result.status == "ok" and usage.model == "gpt-5.6-sol"
    assert len(ai.calls) == 1
    system, user, schema, name = ai.calls[0]
    assert system == load_prompt() and schema is TradeAdviceResponse
    assert name == SCHEMA_NAME and "CANDIDATE 1" in user


def test_advisor_client_is_built_with_an_explicit_timeout() -> None:
    assert ADVICE_TIMEOUT_SECONDS > 0
    client = advisor_client("~/.hermes/profiles/guillotine")
    assert client._timeout == ADVICE_TIMEOUT_SECONDS


def test_facts_withhold_every_number_below_the_coverage_gate() -> None:
    snapshot, scores, candidates = _setup(coverage_pct=Decimal("90.00"))
    facts = build_facts(snapshot, scores, ASKER, ASK, candidates, [])
    assert NO_PROJECTIONS in facts
    assert "projected" not in facts.replace(NO_PROJECTIONS, "")


def test_build_facts_refuses_a_member_the_snapshot_has_no_team_for() -> None:
    snapshot, scores, candidates = _setup()
    with pytest.raises(ValueError):
        build_facts(snapshot, scores, 999, ASK, candidates, [])


@pytest.mark.skipif(
    os.environ.get("UG_LIVE_AI_TESTS") != "1",
    reason="live model calls cost credits; set UG_LIVE_AI_TESTS=1 to run them",
)
def test_live_advice_ranks_only_the_candidates_it_was_handed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one test that spends the subscription -- see the Registrar's twin."""
    if find_hermes_binary() is None:
        pytest.skip("hermes CLI not found")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    snapshot, scores, candidates = _setup()
    client = advisor_client(Settings.model_fields["hermes_profile_home"].default)
    result, _usage = advise(client, snapshot, scores, ASKER, ASK, candidates, [])
    assert result.status in {"ok", "no_good_trades", "insufficient_data"}
    for proposal in result.proposals:
        assert 1 <= proposal.candidate_index <= len(candidates)
        assert proposal.counterparties[0] in {c.counterparty for c in candidates}
