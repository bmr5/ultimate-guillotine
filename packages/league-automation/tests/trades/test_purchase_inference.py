"""Live checks for the omitted seller rule; no writes or messages."""

import os

import pytest

from ultimate_guillotine.ai.hermes import HermesStructuredClient
from ultimate_guillotine.config import Settings
from ultimate_guillotine.core.hermes_cli import find_hermes_binary
from ultimate_guillotine.trades.context import ContextPlayer, ContextTeam, build_registrar_context
from ultimate_guillotine.trades.extract import extract_trade, load_prompt


def test_prompt_requires_unique_other_holder_for_omitted_seller() -> None:
    prompt = load_prompt()
    assert "Missing-seller inference for a purchase" in prompt
    assert "exactly one other league member's roster" in prompt
    assert "Explicitly named parties and explicit transfer" in prompt


@pytest.mark.skipif(
    os.environ.get("UG_LIVE_AI_TESTS") != "1",
    reason="set UG_LIVE_AI_TESTS=1 for live extraction checks",
)
@pytest.mark.parametrize(
    ("holders", "expected_seller"),
    [((1,), "Member01"), ((), None), ((1, 3), None)],
    ids=["unique-seller", "no-holder", "ambiguous-holder"],
)
def test_live_purchase_infers_only_unique_seller(monkeypatch, holders, expected_seller) -> None:
    if find_hermes_binary() is None:
        pytest.skip("hermes CLI not found")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    members = [f"Member0{i}" for i in range(1, 4)]
    context = build_registrar_context(
        2,
        [
            ContextTeam(
                username=name,
                faab_remaining=1000,
                players=(ContextPlayer("Chase Brown", "RB"),) if i in holders else (),
            )
            for i, name in enumerate(members, start=1)
        ],
        [],
    )
    client = HermesStructuredClient(Settings.model_fields["hermes_profile_home"].default)
    extracted, _ = extract_trade(
        client,
        "🚨 Trade alert 🚨 I'm buying Chase Brown for $300",
        2026,
        None,
        members,
        "Member02",
        context,
    )
    if expected_seller is None:
        assert extracted.kind == "unclear", extracted
        return
    assert extracted.kind == "permanent", extracted
    assert {party.name for party in extracted.parties} == {"Member02", expected_seller}
    player = next(asset for asset in extracted.assets if asset.kind == "player")
    assert (player.from_party, player.to_party) == (expected_seller, "Member02")
    payment = next(asset for asset in extracted.assets if asset.amount == 300)
    assert (payment.from_party, payment.to_party) == ("Member02", expected_seller)
