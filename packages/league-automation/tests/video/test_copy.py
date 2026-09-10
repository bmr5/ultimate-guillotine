from ultimate_guillotine.trades.format import party_receives
from ultimate_guillotine.trades.models import MemberRef, TradeAsset, TradeParty, TradeProposal
from ultimate_guillotine.video.copy import (
    ON_AIR_NAMES,
    TradeCopy,
    default_caption,
    on_air_labels,
    trade_copy,
)

GULAG = "🚨 Trade alert 🚨\nMax agrees to go to gulag for Ben in exchange for $200"


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
    assert copy.footer == "THE SOVEREIGN GUILLOTINE LEAGUE · TRADE REGISTRAR"
    assert isinstance(copy, TradeCopy)


def test_no_week_means_no_week_on_the_subline() -> None:
    copy = trade_copy(proposal(effective_week=None), labels={1: "Derek", 2: "Charlie"})
    assert copy.subline == "Derek gets 450 FAAB · Charlie gets Player Alpha"


def gulag_trade() -> TradeProposal:
    """Ben's rehearsal trade of 2026-09-10, as the registrar stored it."""
    return proposal(
        kind="payment",
        effective_week=1,
        parties=[TradeParty(12, "Teranitup16"), TradeParty(11, "benray887")],
        assets=[
            TradeAsset("other", 12, 11, None, None, None, None, "go to gulag for Ben"),
            TradeAsset("usd", 11, 12, None, None, 200, "usd", "$200"),
        ],
        special_terms=["Max agrees to go to gulag for Ben"],
        evidence_excerpt=GULAG,
    )


def test_an_obligation_reads_on_the_bar_as_the_announcer_put_it() -> None:
    """The bar used to say "Ben R gets go to gulag for Ben", and the read written
    from that had the wrong man in the gulag."""
    copy = trade_copy(gulag_trade(), labels={11: "the Commish", 12: "Max"})
    assert copy.subline == "Max gets $200 · Max agrees to go to gulag for Ben · Week 1"
    assert copy.headline == "SOURCES: MAX AND THE COMMISH AGREE TO A TRADE"


def test_the_facts_start_with_the_announcement_and_say_who_owes_whom() -> None:
    copy = trade_copy(gulag_trade(), labels={11: "the Commish", 12: "Max"})
    assert copy.facts == (
        (
            "Announced in the league chat as: 🚨 Trade alert 🚨 Max agrees to go to gulag for Ben "
            "in exchange for $200"
        ),
        "Max owes the Commish: go to gulag for Ben (an obligation, not a player or money)",
        "the Commish gives Max: $200",
        "Special term, in the announcer's words: Max agrees to go to gulag for Ben",
        "Effective week 1",
    )


def test_a_plain_swap_lists_each_side_and_keeps_the_bar_as_it_was() -> None:
    copy = trade_copy(proposal(), labels={1: "Derek", 2: "Charlie"})
    assert copy.facts == (
        "Announced in the league chat as: trade",
        "Derek gives Charlie: Player Alpha",
        "Charlie gives Derek: 450 FAAB",
        "Effective week 3",
    )
    assert copy.subline == "Derek gets 450 FAAB · Charlie gets Player Alpha · Week 3"


def test_the_commissioner_is_the_commish_on_air_and_ben_r_everywhere_else() -> None:
    members = [
        MemberRef(11, "benray887", ("Ben R", "Commish"), "Ben R", "benray887"),
        MemberRef(12, "Teranitup16", ("Max",), "Max", "Teranitup16"),
    ]
    assert on_air_labels(members) == {11: "the Commish", 12: "Max"}
    assert ON_AIR_NAMES == {"benray887": "the Commish"}
