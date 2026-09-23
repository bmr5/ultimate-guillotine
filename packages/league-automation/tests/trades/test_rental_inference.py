"""Exercise missing-owner inference with the real extractor, without writes or sends.

Run with UG_LIVE_AI_TESTS=1. These use synthetic members and fixed rosters so a
future roster sync cannot change the expected answer.
"""

import os

import pytest

from ultimate_guillotine.ai.hermes import HermesStructuredClient
from ultimate_guillotine.config import Settings
from ultimate_guillotine.core.hermes_cli import find_hermes_binary
from ultimate_guillotine.trades.context import ContextPlayer, ContextTeam, build_registrar_context
from ultimate_guillotine.trades.extract import extract_trade, load_prompt
from ultimate_guillotine.trades.models import MemberRef
from ultimate_guillotine.trades.resolve import RosterIndex, resolve_extracted, validate

ALERT = (
    "🚨 Trade Alert 🚨\n\nMember02 rents out Nico Collins for $50 for 1 week.\n\n"
    "He also puts down a deposit of $275"
)
MEMBERS = [MemberRef(i, f"Member0{i}", ()) for i in range(1, 4)]


def test_prompt_limits_missing_owner_inference_to_sender_and_roster_evidence() -> None:
    prompt = " ".join(load_prompt().split())
    assert "resolve references and the missing-owner rule below first" in prompt
    assert "Both missing-owner rules require sender identity and unique ownership evidence" in prompt
    assert "Explicitly named parties and explicit transfer direction always win" in prompt
    assert "Keep the $50 fee and $275 deposit separate" in prompt


@pytest.mark.skipif(
    os.environ.get("UG_LIVE_AI_TESTS") != "1",
    reason="set UG_LIVE_AI_TESTS=1 for live extraction checks",
)
@pytest.mark.parametrize(
    ("announcer", "owners", "text", "expected_owner"),
    [
        ("Member01", (1,), ALERT, 1),
        (None, (1,), ALERT, None),
        ("Member01", (), ALERT, None),
        ("Member01", (3,), ALERT, None),
        ("Member01", (1, 3), ALERT, None),
        ("Member02", (2,), ALERT, None),
        (
            "Member01",
            (1,),
            (
                "🚨 Trade Alert 🚨 Member02 rents Nico Collins from Member03 for $50 for 1 week. "
                "Member02 also puts down a deposit of $275"
            ),
            3,
        ),
        (
            "Member01",
            (1,),
            "🚨 Trade Alert 🚨 Member02 rents out Nico Collins for $50 for 1 week.",
            None,
        ),
    ],
    ids=[
        "sender-owns-player",
        "unknown-sender",
        "missing-roster",
        "third-party-owner",
        "ambiguous-owner",
        "sender-is-named-party",
        "explicit-parties-win",
        "no-renter-evidence",
    ],
)
def test_live_rental_owner_inference(
    monkeypatch: pytest.MonkeyPatch, announcer, owners, text, expected_owner, transfers=""
) -> None:
    if find_hermes_binary() is None:
        pytest.skip("hermes CLI not found")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    context = build_registrar_context(
        2,
        [
            ContextTeam(
                username=m.display_name,
                faab_remaining=1000,
                players=(ContextPlayer("Nico Collins", "WR"),) if m.member_id in owners else (),
            )
            for m in MEMBERS
        ],
        [],
    )
    if transfers:
        context += "\n\nRecent executed player transfers (last 24 hours):\n" + transfers
    client = HermesStructuredClient(Settings.model_fields["hermes_profile_home"].default)
    extracted, usage = extract_trade(
        client, text, 2026, None, [m.display_name for m in MEMBERS], announcer, context
    )
    if expected_owner is None:
        assert extracted.kind == "unclear", extracted
        return

    assert extracted.kind == "rental", extracted
    proposal = resolve_extracted(
        extracted,
        MEMBERS,
        [],
        RosterIndex.empty(),
        2026,
        "dry-run",
        text,
        "test",
        usage.model,
        announcer=next((m for m in MEMBERS if m.display_name == announcer), None),
    )
    validate(proposal)
    assert {p.member_id for p in proposal.parties} == {expected_owner, 2}
    player = next(a for a in proposal.assets if a.kind == "player")
    assert player.player_name == "Nico Collins"
    assert (player.from_member_id, player.to_member_id) == (expected_owner, 2)
    assert "1 week" in (proposal.rental_return_condition or "")
    # Bare dollars may stay in a text asset when the currency is unstated.
    fees = [a for a in proposal.assets if a.amount == 50 or "$50" in (a.description or "")]
    assert len(fees) == 1, proposal
    assert (fees[0].from_member_id, fees[0].to_member_id) == (2, expected_owner)
    assert not any(a.amount == 325 for a in proposal.assets)
    deposits = [a for a in proposal.assets if a.amount == 275]
    assert deposits or any("275" in term and "deposit" in term for term in proposal.special_terms)
    for deposit in deposits:
        assert (deposit.from_member_id, deposit.to_member_id) == (2, expected_owner)
        assert "deposit" in (deposit.description or "").lower()


@pytest.mark.skipif(
    os.environ.get("UG_LIVE_AI_TESTS") != "1",
    reason="set UG_LIVE_AI_TESTS=1 for live extraction checks",
)
@pytest.mark.parametrize(
    ("transfers", "expected_owner"),
    [
        ("Nico Collins: Member01 -> Member02 (current holder)", 1),
        ("Nico Collins: Member03 -> Member02 (current holder)", None),
        ("Nico Collins: Member02 -> Member01 (current holder)", None),
        ("Breece Hall: Member01 -> Member02 (current holder)", None),
        ("", None),
    ],
    ids=[
        "executed-rental",
        "different-seller",
        "reverse-transfer",
        "different-player",
        "no-history",
    ],
)
def test_live_rental_after_execution(monkeypatch, transfers, expected_owner):
    test_live_rental_owner_inference(
        monkeypatch, "Member01", (2,), ALERT, expected_owner, transfers
    )
