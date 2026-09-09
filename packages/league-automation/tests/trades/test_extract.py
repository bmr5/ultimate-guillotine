import os

import httpx
import pytest

from ultimate_guillotine.ai.openrouter import AIUsage, StructuredOutputClient
from ultimate_guillotine.config import Settings
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
    assert PROMPT_VERSION == "2026.1"
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
def test_live_extraction_reads_a_simple_trade() -> None:
    """The one test that spends money. A key being present in the environment is
    not consent to spend it, so this asks for the flag as well."""
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set")
    with httpx.Client() as http:
        client = StructuredOutputClient(
            api_key=os.environ["OPENROUTER_API_KEY"],
            model=Settings.model_fields["trade_extraction_model"].default,
            http=http,
        )
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
