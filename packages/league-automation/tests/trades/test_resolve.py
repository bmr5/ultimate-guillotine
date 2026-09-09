import pytest

from ultimate_guillotine.sleeper.players import Player
from ultimate_guillotine.trades.models import ExtractedAsset, ExtractedParty, ExtractedTrade
from ultimate_guillotine.trades.resolve import (
    MemberRef,
    RosterIndex,
    Unresolved,
    resolve_extracted,
    validate,
)

MEMBERS = [
    MemberRef(1, "Member01", ("m1", "memberone", "nick")),
    MemberRef(2, "Member02", ()),
    MemberRef(3, "Member03", ("nick",)),
    MemberRef(4, "Member04", ()),
]
PLAYERS = [
    Player("p1", "Player Alpha", "WR", "KC", True),
    Player("p2", "Mike Williams", "WR", "NYJ", True),
    Player("p3", "Mike Williams", "WR", "PIT", True),
    Player("KC", "Kansas City Chiefs", "DEF", "KC", True),
]


def extracted(**overrides) -> ExtractedTrade:
    base = {
        "kind": "permanent", "parties": [ExtractedParty(name="member01"), ExtractedParty(name="Member02")],
        "assets": [
            ExtractedAsset(kind="player", from_party="member01", to_party="Member02", player_name="player alpha", amount=None, unit=None, description=None),
            ExtractedAsset(kind="faab", from_party="Member02", to_party="member01", player_name=None, amount=450, unit="faab", description=None),
        ],
        "effective_week": 2, "rental_return_condition": None, "special_terms": [], "referenced_trade_code": None, "unclear_reason": None,
    }
    base.update(overrides)
    return ExtractedTrade(**base)


ROSTERS = RosterIndex({1: frozenset({"p1"}), 2: frozenset({"p2"}), 3: frozenset({"p3"}), 4: frozenset()})


def resolve(e: ExtractedTrade, rosters: RosterIndex = ROSTERS):
    return resolve_extracted(e, MEMBERS, PLAYERS, rosters, 2026, "g1", "🚨 ...", "2026.1", "m")


def test_resolves_members_by_name_or_alias_and_players_by_name() -> None:
    proposal = resolve(extracted(parties=[ExtractedParty(name="memberone"), ExtractedParty(name="Member02")]))
    assert [p.member_id for p in proposal.parties] == [1, 2]
    assert proposal.assets[0].player_id == "p1"
    assert proposal.assets[1].amount == 450 and proposal.assets[1].unit == "faab"


def test_ambiguous_player_name_is_unresolved_with_reason() -> None:
    e = extracted(assets=[ExtractedAsset(kind="player", from_party="member01", to_party="Member02", player_name="Mike Williams", amount=None, unit=None, description=None)])
    with pytest.raises(Unresolved) as info:
        resolve(e)
    assert "Mike Williams" in info.value.reason


def test_ambiguous_member_name_is_settled_by_roster_evidence() -> None:
    # "nick" is Member01 and Member03; only Member01's roster holds Player Alpha, the player sent.
    e = extracted(parties=[ExtractedParty(name="Nick"), ExtractedParty(name="Member02")],
                  assets=[ExtractedAsset(kind="player", from_party="Nick", to_party="Member02",
                                         player_name="Player Alpha", amount=None, unit=None,
                                         description=None)])
    assert [p.member_id for p in resolve(e).parties] == [1, 2]


def test_ambiguous_member_name_without_roster_evidence_is_unresolved() -> None:
    e = extracted(parties=[ExtractedParty(name="Nick"), ExtractedParty(name="Member02")],
                  assets=[ExtractedAsset(kind="faab", from_party="Nick", to_party="Member02",
                                         player_name=None, amount=10, unit="faab", description=None)])
    with pytest.raises(Unresolved) as info:
        resolve(e, RosterIndex.empty())
    assert "which one" in info.value.reason


def test_unknown_member_is_unresolved() -> None:
    with pytest.raises(Unresolved):
        resolve(extracted(parties=[ExtractedParty(name="Nobody"), ExtractedParty(name="Member02")]))


def test_model_flagged_unclear_is_unresolved_with_its_reason() -> None:
    with pytest.raises(Unresolved) as info:
        resolve(extracted(kind="unclear", unclear_reason="No counterparty named"))
    assert info.value.reason == "No counterparty named"


def test_validate_requires_two_parties_one_asset_units_and_return_condition() -> None:
    good = resolve(extracted())
    validate(good)
    with pytest.raises(Unresolved):
        validate(resolve(extracted(parties=[ExtractedParty(name="Member01"), ExtractedParty(name="Member01")])))
    with pytest.raises(Unresolved):
        validate(resolve(extracted(assets=[])))
    with pytest.raises(Unresolved):
        validate(resolve(extracted(kind="rental")))
