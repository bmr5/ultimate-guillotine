from ultimate_guillotine.trades.format import party_receives
from ultimate_guillotine.trades.models import TradeAsset, TradeParty, TradeProposal
from ultimate_guillotine.video.copy import TradeCopy, default_caption, trade_copy


def proposal(**overrides) -> TradeProposal:
    fields = {
        "season": 2026,
        "effective_week": 3,
        "kind": "permanent",
        "parties": [TradeParty(1, "Member01"), TradeParty(2, "Member02")],
        "assets": [
            TradeAsset("player", 1, 2, "p1", "Player Alpha", None, None, None),
            TradeAsset("faab", 2, 1, None, None, 450, "faab", None),
        ],
        "source_message_guid": "g",
        "evidence_excerpt": "trade",
        "prompt_version": "t",
        "model": "t",
    }
    fields.update(overrides)
    return TradeProposal(**fields)


def test_party_receives_is_the_chat_wording() -> None:
    assert party_receives(proposal(), 2) == "Player Alpha"
    assert party_receives(proposal(), 1) == "450 FAAB"


def test_headline_names_the_player_and_who_gets_him_in_upper_case() -> None:
    copy = trade_copy(proposal(), labels={1: "Derek", 2: "Charlie"})
    assert copy.headline == "SOURCES: PLAYER ALPHA TRADED TO CHARLIE"


def test_subline_says_what_each_side_gets_and_the_week() -> None:
    copy = trade_copy(proposal(), labels={1: "Derek", 2: "Charlie"})
    assert copy.subline == "Derek gets 450 FAAB · Charlie gets Player Alpha · Week 3"


def test_labels_fall_back_to_the_stored_display_name() -> None:
    copy = trade_copy(proposal())
    assert copy.headline == "SOURCES: PLAYER ALPHA TRADED TO MEMBER02"
    assert copy.subline.startswith("Member01 gets 450 FAAB")


def test_a_trade_without_a_player_gets_the_parties_headline() -> None:
    faab_only = proposal(assets=[TradeAsset("faab", 2, 1, None, None, 450, "faab", None)])
    copy = trade_copy(faab_only, labels={1: "Derek", 2: "Charlie"})
    assert copy.headline == "SOURCES: DEREK AND CHARLIE AGREE TO A TRADE"


def test_caption_defaults_to_the_pov_line_and_can_be_overridden() -> None:
    assert default_caption(["Derek", "Charlie"]) == (
        "pov: the league chat when Derek and Charlie pull off a trade nobody saw coming"
    )
    copy = trade_copy(proposal(), caption="pov: me reading the trade alert at 2am")
    assert copy.caption == "pov: me reading the trade alert at 2am"
    assert copy.tag == "BREAKING NEWS"
    assert isinstance(copy, TradeCopy)


def test_no_week_means_no_week_on_the_subline() -> None:
    copy = trade_copy(proposal(effective_week=None), labels={1: "Derek", 2: "Charlie"})
    assert copy.subline == "Derek gets 450 FAAB · Charlie gets Player Alpha"
