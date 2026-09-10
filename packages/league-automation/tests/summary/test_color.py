"""The colour: what the model is asked, and what of its answer is allowed through.

The verifier is the whole safety of the feature: a headline and a blurb may only
carry numbers that are in the facts, and nothing that looks like private data.
"""

from decimal import Decimal

import pytest

from tests.summary.helpers import done_team, snapshot
from ultimate_guillotine.ai.structured import AIUsage
from ultimate_guillotine.summary.color import (
    COLOR_TIMEOUT_SECONDS,
    PROMPT_VERSION,
    ColorRejected,
    EodColor,
    color_client,
    load_prompt,
    verify_color,
    write_color,
)
from ultimate_guillotine.summary.models import EodPacket
from ultimate_guillotine.summary.render import facts_text
from ultimate_guillotine.summary.survival import simulate

LABELS = ("Member01", "Member02", "Member03", "Member04")


def _facts() -> str:
    snap = snapshot(
        (done_team(1, "100"), done_team(2, "90.5"), done_team(3, "80"), done_team(4, "70.5")),
        week=1,
        day_state="final",
        games_final=16,
        games_total=16,
    )
    packet = EodPacket(
        snapshot=snap,
        result=simulate(snap, simulations=50),
        coverage_pct=Decimal(100),
        no_odds_reason=None,
    )
    return facts_text(packet)


def _color(headline: str = "Two graves dug", blurb: str = "Member04 goes down at 70.5."):
    return EodColor(headline=headline, blurb=blurb)


# -- the verifier ---------------------------------------------------------


def test_a_faithful_colour_passes_unchanged() -> None:
    color = _color()
    assert verify_color(color, _facts(), LABELS) == color


def test_a_number_not_in_the_facts_is_rejected() -> None:
    with pytest.raises(ColorRejected, match="number not in the facts: 71.9"):
        verify_color(_color(blurb="Member04 sits at 71.9 tonight."), _facts(), LABELS)


def test_a_rounded_score_and_a_small_count_are_allowed() -> None:
    """ "Member04 at 70" is 70.5 rounded down; "two teams" is a count. Neither is an
    invention, and refusing them would refuse most sentences a person writes."""
    color = _color(blurb="Member04 is stuck at 70 and 2 teams are heading down.")
    assert verify_color(color, _facts(), LABELS) == color


def test_a_percentage_the_facts_carry_is_allowed() -> None:
    facts = _facts()
    assert "locked" in facts
    color = _color(blurb="Member03 at 80 is locked in with Member04.")
    assert verify_color(color, facts, LABELS) == color


@pytest.mark.parametrize(
    "blurb",
    [
        "Call Member04 at 555-555-0100 to console him.",
        "Email member04@example.com with condolences.",
        "Member04 still owes dues.",
        "See https://example.com for the odds.",
        "The chat is iMessage;-;chat123456 by the way.",
    ],
)
def test_private_data_patterns_are_rejected(blurb: str) -> None:
    with pytest.raises(ColorRejected, match="private-data pattern"):
        verify_color(_color(blurb=blurb), _facts(), LABELS)


def test_markdown_asterisks_are_stripped_not_rejected() -> None:
    color = _color(headline="**Two graves dug**", blurb="Member04 goes *down* at 70.5.")
    checked = verify_color(color, _facts(), LABELS)
    assert checked.headline == "Two graves dug"
    assert checked.blurb == "Member04 goes down at 70.5."


def test_a_blank_headline_after_stripping_is_rejected() -> None:
    with pytest.raises(ColorRejected, match="empty"):
        verify_color(_color(headline="***"), _facts(), LABELS)


# -- the call -------------------------------------------------------------


class FakeClient:
    def __init__(self, answer: EodColor) -> None:
        self.answer = answer
        self.calls: list[tuple[str, str, type, str]] = []

    def parse(self, system: str, user: str, schema, schema_name: str):
        self.calls.append((system, user, schema, schema_name))
        return self.answer, AIUsage("session-1", 0, 0, "fake-model")


def test_write_color_hands_the_model_the_prompt_and_the_facts_as_data() -> None:
    client = FakeClient(_color())
    facts = _facts()
    color, usage = write_color(client, facts, week=1, day_state="final")

    assert color == _color()
    assert usage.model == "fake-model"
    system, user, schema, schema_name = client.calls[0]
    assert schema is EodColor and schema_name == "EodColor"
    assert f"prompt_version: {PROMPT_VERSION}" in system
    assert "Week 1" in user and "final" in user
    assert facts in user
    assert user.index("FACTS") < user.index(facts)


def test_the_prompt_file_is_versioned_and_states_the_rules() -> None:
    prompt = load_prompt()
    assert f"prompt_version: {PROMPT_VERSION}" in prompt
    for word in ("never", "number", "dues"):
        assert word in prompt.lower()


def test_the_colour_client_states_its_own_timeout() -> None:
    seen: dict = {}

    def runner(command, **kwargs):
        seen.update(kwargs)
        raise OSError("not actually running hermes")

    client = color_client("/nonexistent/profile", runner=runner, binary="/bin/false")
    with pytest.raises(Exception):  # noqa: B017 - only the recorded timeout matters
        client.parse("s", "u", EodColor, "EodColor")
    assert seen["timeout"] == COLOR_TIMEOUT_SECONDS
