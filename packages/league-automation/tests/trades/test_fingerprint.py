from ultimate_guillotine.trades.fingerprint import (
    message_fingerprint,
    trade_context_key,
    trade_fingerprint,
)
from ultimate_guillotine.trades.models import TradeAsset, TradeParty, TradeProposal


def proposal(**overrides) -> TradeProposal:
    base = {
        "season": 2026, "effective_week": 2, "kind": "permanent",
        "parties": [TradeParty(1, "Member01"), TradeParty(2, "Member02")],
        "assets": [
            TradeAsset("player", 1, 2, "p1", "Player Alpha", None, None, None),
            TradeAsset("faab", 2, 1, None, None, 450, "faab", None),
        ],
        "rental_return_condition": None, "special_terms": [], "referenced_trade_code": None,
        "source_message_guid": "g1", "evidence_excerpt": "🚨 ...", "prompt_version": "2026.1",
        "model": "m",
    }
    base.update(overrides)
    return TradeProposal(**base)


def test_message_fingerprint_ignores_case_and_whitespace() -> None:
    assert message_fingerprint("🚨 A  sends B") == message_fingerprint("🚨 a sends b\n")


def test_trade_fingerprint_ignores_order_and_source() -> None:
    reordered = proposal(
        parties=[TradeParty(2, "Member02"), TradeParty(1, "Member01")],
        assets=list(reversed(proposal().assets)), source_message_guid="g2", evidence_excerpt="x",
    )
    assert trade_fingerprint(proposal()) == trade_fingerprint(reordered)
    assert len(trade_fingerprint(proposal())) == 64


def test_trade_fingerprint_changes_with_amount_or_week_or_return_condition() -> None:
    amended = proposal(assets=[proposal().assets[0], TradeAsset("faab", 2, 1, None, None, 500, "faab", None)])
    assert trade_fingerprint(amended) != trade_fingerprint(proposal())
    assert trade_fingerprint(proposal(effective_week=3)) != trade_fingerprint(proposal())
    assert trade_fingerprint(proposal(rental_return_condition="returned Monday")) != trade_fingerprint(proposal())


def test_context_key_is_stable_across_amounts() -> None:
    amended = proposal(assets=[proposal().assets[0], TradeAsset("faab", 2, 1, None, None, 500, "faab", None)])
    assert trade_context_key(amended) == trade_context_key(proposal())
    assert trade_context_key(proposal(parties=[TradeParty(1, "Member01"), TradeParty(3, "Member03")])) != trade_context_key(proposal())
