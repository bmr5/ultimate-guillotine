from ultimate_guillotine.trades.format import (
    format_clarification,
    format_confirmation,
    format_rescinded,
    format_terms,
    format_updated,
    party_labels,
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


def test_confirmation_is_one_line_naming_the_parties() -> None:
    # Ben (2026-09-10): the chat gets a confirmation and nothing else.
    text = format_confirmation("T-2026-014", proposal())
    assert text == "🚨 Trade T-2026-014 logged · Max ↔ Evan"
    assert "\n" not in text


def test_confirmation_uses_the_board_labels_when_it_has_them() -> None:
    class Member:
        def __init__(self, member_id, nickname, sleeper_display_name):
            self.member_id = member_id
            self.nickname = nickname
            self.sleeper_display_name = sleeper_display_name

    labels = party_labels(
        [Member(1, "Max R", None), Member(2, None, "Evan Display"), Member(3, None, None)]
    )
    assert labels == {1: "Max R", 2: "Evan Display"}
    text = format_confirmation("T-2026-014", proposal(), labels)
    assert text == "🚨 Trade T-2026-014 logged · Max R ↔ Evan Display"
    assert format_updated("T-2026-014", proposal(), {"assets": []}, labels) == (
        "🚨 Trade T-2026-014 updated · Max R ↔ Evan Display"
    )


def test_terms_match_spec_layout() -> None:
    text = format_terms(proposal())
    assert text.splitlines() == [
        "Max receives: Ja'Marr Chase",
        "Evan receives: DJ Moore + 450 FAAB",
        "Week 2 · Permanent",
    ]


def test_rental_shows_return_condition_and_special_terms() -> None:
    text = format_terms(
        proposal(
            kind="rental",
            rental_return_condition="returns after Week 4",
            special_terms=["no gulag protection"],
        ),
    )
    assert "Week 2 · Rental (returns after Week 4)" in text
    assert "Terms: no gulag protection" in text


def test_updated_and_rescinded_and_clarification() -> None:
    assert format_updated("T-2026-014", proposal(), {"assets": []}) == (
        "🚨 Trade T-2026-014 updated · Max ↔ Evan"
    )
    assert format_rescinded("T-2026-014") == "🚨 Trade T-2026-014 rescinded"
    assert format_clarification("Two players named Mike Williams; which team?") == (
        "🚨 Trade not logged yet: Two players named Mike Williams; which team? "
        "Reply with a corrected 🚨 Trade alert 🚨."
    )


def test_party_receiving_nothing_says_nothing() -> None:
    text = format_terms(
        proposal(assets=[TradeAsset("player", 2, 1, "p1", "Ja'Marr Chase", None, None, None)]),
    )
    assert "Evan receives: nothing" in text


def test_unknown_week_renders_question_mark() -> None:
    text = format_terms(proposal(effective_week=None))
    assert "Week ? · Permanent" in text


def test_dollars_draft_dollars_and_protection_render() -> None:
    text = format_terms(
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
    text = format_terms(proposal(), previous)
    assert text.splitlines()[-1] == "Was: 200 FAAB"


def test_updated_omits_was_line_when_amounts_match() -> None:
    previous = proposal().model_dump(mode="json")
    text = format_terms(proposal(), previous)
    assert "Was:" not in text


def test_updated_says_nothing_when_previous_had_no_amounts() -> None:
    text = format_terms(proposal(), {"assets": []})
    assert text.splitlines()[-1] == "Was: nothing"


def test_assets_no_party_receives_are_listed_after_the_parties() -> None:
    text = format_terms(
        proposal(
            assets=[
                TradeAsset("player", 2, 1, "p1", "Ja'Marr Chase", None, None, None),
                TradeAsset("faab", 1, None, None, None, 100, "faab", None),
                TradeAsset("other", 2, 3, None, None, None, None, "a bye week favor"),
            ]
        ),
    )
    assert text.splitlines() == [
        "Max receives: Ja'Marr Chase",
        "Evan receives: nothing",
        "Also: 100 FAAB + a bye week favor",
        "Week 2 · Permanent",
    ]


def test_protection_with_an_amount_still_reads_as_its_description() -> None:
    text = format_terms(
        proposal(assets=[TradeAsset("protection", 1, 2, None, None, 1, None, "gulag protection")]),
    )
    assert "Evan receives: gulag protection" in text


def test_negative_usd_and_zero_faab_render_readably() -> None:
    text = format_terms(
        proposal(
            kind="payment",
            assets=[
                TradeAsset("usd", 1, 2, None, None, -25, "usd", None),
                TradeAsset("faab", 1, 2, None, None, 0, "faab", None),
            ],
        ),
    )
    assert "Evan receives: -$25 + 0 FAAB" in text


def test_amount_without_a_unit_falls_back_to_the_asset_kind() -> None:
    text = format_terms(
        proposal(assets=[TradeAsset("faab", 1, 2, None, None, 450, None, None)]),
    )
    assert "Evan receives: 450 FAAB" in text


def test_rental_without_a_return_condition_says_only_rental() -> None:
    text = format_terms(proposal(kind="rental", rental_return_condition=None))
    assert "Week 2 · Rental" in text.splitlines()


def test_player_without_a_name_or_id_still_appears() -> None:
    text = format_terms(
        proposal(assets=[TradeAsset("player", 1, 2, None, None, None, None, None)]),
    )
    assert "Evan receives: a player" in text


def test_the_was_line_ignores_assets_that_are_not_amounts() -> None:
    """A `protection` asset carrying a stray number is a term, not an amount:
    counting it would print a `Was:` line for a trade whose amounts never moved."""
    previous = proposal(
        assets=[
            proposal().assets[2],
            TradeAsset("protection", 1, 2, None, None, 1, None, "gulag protection"),
        ]
    )
    current = proposal(
        assets=[
            proposal().assets[2],
            TradeAsset("protection", 1, 2, None, None, 2, None, "gulag protection"),
        ]
    )
    text = format_terms(current, previous.model_dump(mode="json"))
    assert "Was:" not in text
