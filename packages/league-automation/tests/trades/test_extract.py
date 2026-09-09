import os

import pytest

from ultimate_guillotine.ai.hermes import HermesStructuredClient
from ultimate_guillotine.ai.structured import AIUsage
from ultimate_guillotine.config import Settings
from ultimate_guillotine.core.hermes_cli import find_hermes_binary
from ultimate_guillotine.trades.extract import PROMPT_VERSION, extract_trade, load_prompt
from ultimate_guillotine.trades.models import ExtractedAsset, ExtractedParty, ExtractedTrade


class FakeAI:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def parse(self, system, user, schema, schema_name):
        self.calls.append((system, user, schema, schema_name))
        return self.result, AIUsage("gen-1", 10, 5, "m")


def test_prompt_is_versioned_and_states_the_rules() -> None:
    prompt = load_prompt()
    assert PROMPT_VERSION == "2026.2"
    assert prompt.startswith(f"<!-- prompt_version: {PROMPT_VERSION} -->")
    assert "verbatim" in prompt and "null" in prompt and "fairness" in prompt


def test_prompt_explains_rentals_and_keeps_special_terms_for_other_conditions() -> None:
    prompt = load_prompt()
    assert "`rental_return_condition` (for example `50 FAAB returned Monday`)" in prompt
    assert "use `special_terms` only for other unusual conditions" in prompt


def test_prompt_orders_not_a_trade_before_unclear_and_scopes_naming() -> None:
    prompt = load_prompt()
    assert "Decide `not_a_trade` first" in prompt
    assert "Only when the message announces a transaction" in prompt
    assert "in the announcement itself" in prompt
    assert "one-sentence `unclear_reason`" in prompt
    assert prompt.index("Decide `not_a_trade` first") < prompt.index("`unclear_reason`")


#: The rules 2026.2 added, each as the phrase the prompt has to carry. Kept as a
#: table so a rule quietly dropped from the prompt fails under its own name --
#: the suite proves the prompt still says these things, never what the model
#: does with them, which is what `scripts/registrar_cases.py` is for.
PROMPT_RULES_2026_2 = [
    (
        "a report of an alert is not an announcement",
        "A message that reports or reacts to an alert instead of making one is `not_a_trade`",
    ),
    (
        "quoting or forwarding someone else's alert",
        "quoting or forwarding someone else's alert, or commenting on one",
    ),
    (
        "an aside on your own alert is still an announcement",
        "An aside attached to the announcer's own alert",
    ),
    (
        "another league's trade names no member",
        "An alert that names nobody from the `League members` list is another league's trade",
    ),
    (
        "one named member is enough",
        "One league member named in the announcement is enough to make it this league's alert",
    ),
    (
        "unstated direction is unclear, with a reason",
        "Also `unclear`, with a one-sentence `unclear_reason`:",
    ),
    (
        "unstated direction is the never-says-which-side case",
        "names the people and the assets but never says which side gives what",
    ),
    (
        "what does count as stating direction",
        "Direction is stated by words and marks like `sends`, `to`, `for`, `gets`, `->`",
    ),
]


@pytest.mark.parametrize(
    ("rule", "phrase"),
    PROMPT_RULES_2026_2,
    ids=[rule for rule, _ in PROMPT_RULES_2026_2],
)
def test_prompt_states_the_2026_2_rules(rule: str, phrase: str) -> None:
    # The prompt wraps at 100 columns, so match against it as one flowing line.
    assert phrase in " ".join(load_prompt().split())


def test_prompt_keeps_the_not_a_trade_rules_ahead_of_the_unclear_rules() -> None:
    """Order is the rule: a report of someone else's alert has to be answered
    `not_a_trade` before the direction test can turn it into a clarification."""
    prompt = " ".join(load_prompt().split())
    assert prompt.index("reports or reacts to an alert") < prompt.index("`unclear_reason`")
    assert prompt.index("names nobody from the `League members` list") < prompt.index(
        "never says which side gives what"
    )


def test_prompt_marks_the_user_message_context_lines_as_never_announcement() -> None:
    prompt = load_prompt()
    assert "The user message's `Season:`, `Week hint:`, and `League members` lines are" in prompt
    assert "context, never announcement content" in prompt
    assert "A name that appears only on those lines is not named." in prompt
    assert "The `Week hint:` line is context and never counts as the announcement" in prompt


def test_prompt_explains_referenced_trade_code_and_asset_fields() -> None:
    prompt = load_prompt()
    assert "a code such as `T-2026-014`" in prompt
    assert "copy that code into `referenced_trade_code`" in prompt
    assert "`from_party` is the person who gives the asset" in prompt
    assert "`to_party` is the person who receives it" in prompt
    assert "`protection` is for gulag protection" in prompt
    assert "Use asset `kind` `other` for anything else" in prompt
    assert "verbatim `description`" in prompt


def test_extract_passes_context_and_returns_model_output() -> None:
    expected = ExtractedTrade(
        kind="rental", parties=[ExtractedParty(name="Member03"), ExtractedParty(name="Member04")],
        assets=[ExtractedAsset(kind="player", from_party="Member04", to_party="Member03", player_name="Player Beta", amount=None, unit=None, description=None),
                ExtractedAsset(kind="faab", from_party="Member03", to_party="Member04", player_name=None, amount=92, unit="faab", description=None)],
        effective_week=2, rental_return_condition="50 FAAB returned Monday", special_terms=[], referenced_trade_code=None, unclear_reason=None,
    )
    ai = FakeAI(expected)
    result, usage = extract_trade(ai, "🚨 Member03 rents Player Beta from Member04 for 92 FAAB, 50 returned Monday", 2026, 2, ["Member03", "Member04"])
    assert result == expected and usage.response_id == "gen-1"
    system, user, schema, name = ai.calls[0]
    assert schema is ExtractedTrade and name == "extracted_trade"
    assert "Member03" in user and "Season: 2026" in user and "Week hint: 2" in user
    assert system == load_prompt()


def test_extract_writes_the_exact_context_lines() -> None:
    ai = FakeAI(ExtractedTrade(kind="not_a_trade"))
    extract_trade(ai, "Member03 rents Player Beta", 2026, 2, ["Member03", "Member04"])
    lines = ai.calls[0][1].splitlines()
    assert "Season: 2026" in lines
    assert "Week hint: 2" in lines
    assert "League members (Sleeper username: names people use): Member03; Member04" in lines

    extract_trade(ai, "Member03 rents Player Beta", 2026, None, ["Member03", "Member04"])
    assert "Week hint: unknown" in ai.calls[1][1].splitlines()


@pytest.mark.skipif(
    os.environ.get("UG_LIVE_AI_TESTS") != "1",
    reason="live model calls cost credits; set UG_LIVE_AI_TESTS=1 to run them",
)
def test_live_extraction_reads_a_simple_trade(monkeypatch: pytest.MonkeyPatch) -> None:
    """The one test that spends the subscription. A configured Hermes profile is
    not consent to call it, so this asks for the flag as well.

    `PYTEST_CURRENT_TEST` is dropped from this process's environment, and so from
    the CLI's: Hermes reads it as "I am running inside my own test suite" and then
    refuses to open the real user's auth store, which leaves the call with no
    credentials. Nothing in the package sets that variable, so only a test run is
    ever affected; it is dropped here rather than in the client so that the client
    keeps handing the CLI the environment it was actually given. Hermes still
    declines to write a session row, which is exactly right for a test.
    """
    if find_hermes_binary() is None:
        pytest.skip("hermes CLI not found")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    client = HermesStructuredClient(Settings.model_fields["hermes_profile_home"].default)
    result, _usage = extract_trade(
        client,
        "🚨 Trade Alert 🚨\nMember01 sends Player Alpha to Member02 for 100 FAAB",
        2026,
        None,
        ["Member01: Ben, Benny", "Member02: no known nicknames"],
    )
    assert result.kind == "permanent"
    assert len(result.parties) == 2
    faab = [asset for asset in result.assets if asset.unit == "faab"]
    assert len(faab) == 1
    assert faab[0].amount == 100


def test_prompt_names_every_asset_kind_and_ties_units_to_money_kinds() -> None:
    # The prompt wraps at 100 columns, so match against it as one flowing line.
    prompt = " ".join(load_prompt().split())
    assert (
        "Asset `kind` is one of `player`, `faab` (waiver budget), `usd` (real money), "
        "`draft_dollars` (auction budget), `protection`, or `other`." in prompt
    )
    assert "`unit` must match the kind" in prompt
