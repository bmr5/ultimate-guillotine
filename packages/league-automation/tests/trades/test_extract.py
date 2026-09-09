import os

import httpx
import pytest

from ultimate_guillotine.ai.openrouter import AIUsage, StructuredOutputClient
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
    assert "verbatim" in prompt and "null" in prompt and "fairness" in prompt


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


@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set",
)
def test_live_extraction_reads_a_simple_trade() -> None:
    with httpx.Client() as http:
        client = StructuredOutputClient(
            api_key=os.environ["OPENROUTER_API_KEY"],
            model="openai/gpt-5-mini",
            http=http,
        )
        result, _usage = extract_trade(
            client,
            "🚨 Trade Alert 🚨\nMember01 sends Player Alpha to Member02 for 100 FAAB",
            2026,
            None,
            ["Member01", "Member02"],
        )
    assert result.kind == "permanent"
    assert len(result.parties) == 2
    faab = [asset for asset in result.assets if asset.unit == "faab"]
    assert len(faab) == 1
    assert faab[0].amount == 100
