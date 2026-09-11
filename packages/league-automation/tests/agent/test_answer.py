"""The one shape the agent's final turn must take, and what it may not carry."""

import json

import pytest
from pydantic import ValidationError

from ultimate_guillotine.agent.answer import (
    CHAT_TEXT_LIMIT,
    LeagueAnswer,
    ProposalLeg,
    extract_answer,
)
from ultimate_guillotine.ai.structured import AIInvalidOutput
from ultimate_guillotine.core.signature import sign


def _answer(**overrides) -> dict:
    base = {
        "kind": "answer",
        "chat_text": "Member01 has the most FAAB: 960.",
        "report": None,
        "facts": {"players": [], "faab": [{"member": "Member01", "amount": 960,
                                          "claim": "balance"}], "proposals": []},
        "source_line": "Source: FAAB as of 3:00pm",
    }
    return {**base, **overrides}


def test_the_answer_is_read_out_of_prose_and_a_fence() -> None:
    text = "Here you go.\n```json\n" + json.dumps(_answer()) + "\n```\nDone."
    answer = extract_answer(text)
    assert answer.kind == "answer"
    assert answer.facts.faab[0].amount == 960
    assert answer.report is None


def test_a_report_carries_its_sources_and_a_restated_question() -> None:
    report = {
        "title": "Holding Bowers this week",
        "question": "Which team could hold Brock Bowers for a week, and for what?",
        "html_body": "<h2>Options</h2><p class='card'>...</p>",
        "sources": [{"url": "https://example.com/bowers", "claim": "Bowers is out 1-2 weeks"}],
    }
    answer = LeagueAnswer.model_validate(_answer(report=report))
    assert answer.report is not None
    assert answer.report.sources[0].url.startswith("https://")


def test_a_term_leg_carries_text_and_a_player_leg_carries_a_player() -> None:
    term = ProposalLeg(kind="term", text="returns before the Week 11 lock",
                       from_member="Member02", to_member="Member05")
    assert term.text
    with pytest.raises(ValidationError):
        ProposalLeg(kind="player", from_member="Member02", to_member="Member05")
    with pytest.raises(ValidationError):
        ProposalLeg(kind="faab", from_member="Member02", to_member="Member05")
    with pytest.raises(ValidationError):
        ProposalLeg(kind="cash", amount=20, from_member="Member02", to_member="Member05")


def test_a_clarification_carries_no_report() -> None:
    report = {"title": "t", "question": "q", "html_body": "<p>x</p>", "sources": []}
    with pytest.raises(ValidationError):
        LeagueAnswer.model_validate(_answer(kind="clarification", report=report))


@pytest.mark.parametrize("report", [
    None,
    {"title": "Full result", "html_body": "<p>Long details.</p>" * 100, "sources": []},
])
def test_chat_text_is_bounded(report) -> None:
    assert len(sign("x" * CHAT_TEXT_LIMIT)) == 129
    answer = LeagueAnswer.model_validate(_answer(chat_text="x" * CHAT_TEXT_LIMIT, report=report))
    assert len(sign(answer.chat_text)) == 129
    with pytest.raises(ValidationError):
        LeagueAnswer.model_validate(_answer(chat_text="x" * (CHAT_TEXT_LIMIT + 1), report=report))


def test_fixed_agent_replies_also_fit_the_message_limit() -> None:
    from ultimate_guillotine.agent.trigger import RECEIPT, REFUSAL
    from ultimate_guillotine.agent.worker import ATTACHMENT_FAILED, COULD_NOT_FINISH

    for text in (RECEIPT, REFUSAL, ATTACHMENT_FAILED, COULD_NOT_FINISH):
        assert len(sign(text)) <= 129


def test_anything_but_the_contract_is_invalid_output() -> None:
    with pytest.raises(AIInvalidOutput):
        extract_answer("I could not decide.")
