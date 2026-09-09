from ultimate_guillotine.trades.format import (
    format_clarification,
    format_confirmation,
    format_rescinded,
    format_updated,
)
from ultimate_guillotine.trades.models import TradeAsset, TradeParty, TradeProposal


def proposal(**overrides) -> TradeProposal:
    base = {
        "season": 2026,
        "effective_week": 2,
        "kind": "permanent",
        "parties": [TradeParty(1, "Max"), TradeParty(2, "Evan")],
        "assets": [
            TradeAsset("player", 2, 1, "p1", "Ja'Marr Chase", None, None, None),
            TradeAsset("player", 1, 2, "p2", "DJ Moore", None, None, None),
            TradeAsset("faab", 1, 2, None, None, 450, "faab", None),
        ],
        "rental_return_condition": None,
        "special_terms": [],
        "referenced_trade_code": None,
        "source_message_guid": "g",
        "evidence_excerpt": "e",
        "prompt_version": "2026.1",
        "model": "m",
    }
    base.update(overrides)
    return TradeProposal(**base)


def test_confirmation_matches_spec_layout() -> None:
    text = format_confirmation("T-2026-014", proposal())
    assert text.splitlines() == [
        "🚨 Trade T-2026-014 logged",
        "Max receives: Ja'Marr Chase",
        "Evan receives: DJ Moore + 450 FAAB",
        "Week 2 · Permanent",
    ]


def test_rental_shows_return_condition_and_special_terms() -> None:
    text = format_confirmation(
        "T-2026-015",
        proposal(
            kind="rental",
            rental_return_condition="returns after Week 4",
            special_terms=["no gulag protection"],
        ),
    )
    assert "Week 2 · Rental (returns after Week 4)" in text
    assert "Terms: no gulag protection" in text


def test_updated_and_rescinded_and_clarification() -> None:
    assert format_updated("T-2026-014", proposal(), {"assets": []}).startswith(
        "🚨 Trade T-2026-014 updated"
    )
    assert format_rescinded("T-2026-014") == "🚨 Trade T-2026-014 rescinded"
    assert format_clarification("Two players named Mike Williams; which team?") == (
        "🚨 Trade not logged yet: Two players named Mike Williams; which team? "
        "Reply with a corrected 🚨 alert."
    )


def test_party_receiving_nothing_says_nothing() -> None:
    text = format_confirmation(
        "T-2026-016",
        proposal(assets=[TradeAsset("player", 2, 1, "p1", "Ja'Marr Chase", None, None, None)]),
    )
    assert "Evan receives: nothing" in text


def test_unknown_week_renders_question_mark() -> None:
    text = format_confirmation("T-2026-017", proposal(effective_week=None))
    assert "Week ? · Permanent" in text


def test_dollars_draft_dollars_and_protection_render() -> None:
    text = format_confirmation(
        "T-2026-018",
        proposal(
            kind="payment",
            assets=[
                TradeAsset("usd", 1, 2, None, None, 25, "usd", None),
                TradeAsset("draft_dollars", 1, 2, None, None, 30, "draft_dollars", None),
                TradeAsset("protection", 1, 2, None, None, None, None, "gulag immunity Week 3"),
            ],
        ),
    )
    assert "Evan receives: $25 + 30 draft dollars + gulag immunity Week 3" in text
    assert "Week 2 · Payment" in text


def test_updated_lists_previous_amounts_when_they_change() -> None:
    previous = proposal(
        assets=[TradeAsset("faab", 1, 2, None, None, 200, "faab", None)]
    ).model_dump(mode="json")
    text = format_updated("T-2026-014", proposal(), previous)
    assert text.splitlines()[-1] == "Was: 200 FAAB"


def test_updated_omits_was_line_when_amounts_match() -> None:
    previous = proposal().model_dump(mode="json")
    text = format_updated("T-2026-014", proposal(), previous)
    assert "Was:" not in text


def test_updated_says_nothing_when_previous_had_no_amounts() -> None:
    text = format_updated("T-2026-014", proposal(), {"assets": []})
    assert text.splitlines()[-1] == "Was: nothing"
