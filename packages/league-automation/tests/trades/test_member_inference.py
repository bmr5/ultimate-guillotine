import pytest

from ultimate_guillotine.sleeper.players import Player
from ultimate_guillotine.trades.models import (
    ExtractedAsset,
    ExtractedParty,
    ExtractedTrade,
    MemberRef,
)
from ultimate_guillotine.trades.resolve import RosterIndex, Unresolved, resolve_extracted

PLAYERS = [
    Player("p1", "Rashaan Bellwether", "WR", "KC", True),
    Player("p2", "Gavin Tolliver", "RB", "BUF", True),
]


def resolve(name, assets, holdings, *, other="Member03"):
    members = [
        MemberRef(1, "Member01", (name, f"{name} R")),
        MemberRef(2, "Member02", (f"{name} T",)),
        MemberRef(3, "Member03", ()),
    ]
    return resolve_extracted(
        ExtractedTrade(
            kind="permanent",
            parties=[ExtractedParty(name=name), ExtractedParty(name=other)],
            assets=assets,
        ),
        members,
        PLAYERS,
        RosterIndex({k: frozenset(v) for k, v in holdings.items()}),
        2026,
        "test",
        "synthetic alert",
        "test",
        "test",
    )


@pytest.mark.parametrize("name", ["Nick", "Brandon", "Ben"])
@pytest.mark.parametrize("player_name", ["Rashaan Bellwether", "Rashaan"])
def test_shared_first_name_uses_player_owner_even_when_one_has_exact_alias(name, player_name):
    proposal = resolve(
        name,
        [
            ExtractedAsset(
                kind="player", from_party=name, to_party="Member03", player_name=player_name
            )
        ],
        {1: ["p2"], 2: ["p1"], 3: []},
    )
    assert {p.member_id for p in proposal.parties} == {2, 3}
    assert proposal.assets[0].from_member_id == 2
    assert proposal.assets[0].player_id == "p1"


@pytest.mark.parametrize("name", ["Nick", "Brandon", "Ben"])
def test_money_only_shared_name_requires_clarification(name):
    with pytest.raises(Unresolved, match="which one"):
        resolve(
            name,
            [ExtractedAsset(kind="faab", from_party=name, to_party="Member03", amount=50)],
            {1: ["p2"], 2: ["p1"], 3: []},
        )


def test_player_identifies_seller_but_cannot_identify_which_buyer():
    with pytest.raises(Unresolved, match="which one"):
        resolve(
            "Alex",
            [
                ExtractedAsset(
                    kind="player",
                    from_party="Member03",
                    to_party="Alex",
                    player_name="Rashaan Bellwether",
                )
            ],
            {1: [], 2: ["p2"], 3: ["p1"]},
        )


@pytest.mark.parametrize("holdings", [{}, {1: [], 2: [], 3: ["p1"]}, {1: ["p1"], 2: ["p1"]}])
def test_missing_moved_or_conflicting_ownership_requires_clarification(holdings):
    with pytest.raises(Unresolved, match="which one"):
        resolve(
            "Alex",
            [
                ExtractedAsset(
                    kind="player",
                    from_party="Alex",
                    to_party="Member03",
                    player_name="Rashaan Bellwether",
                )
            ],
            holdings,
        )


def test_both_shared_names_resolve_from_players_given_in_a_swap():
    members = [
        MemberRef(1, "Member01", ("Alex R",)),
        MemberRef(2, "Member02", ("Alex T",)),
        MemberRef(3, "Member03", ("Sam R",)),
        MemberRef(4, "Member04", ("Sam T",)),
    ]
    proposal = resolve_extracted(
        ExtractedTrade(
            kind="permanent",
            parties=[ExtractedParty(name="Alex"), ExtractedParty(name="Sam")],
            assets=[
                ExtractedAsset(
                    kind="player",
                    from_party="Alex",
                    to_party="Sam",
                    player_name="Rashaan Bellwether",
                ),
                ExtractedAsset(
                    kind="player", from_party="Sam", to_party="Alex", player_name="Gavin Tolliver"
                ),
            ],
        ),
        members,
        PLAYERS,
        RosterIndex({1: frozenset(), 2: frozenset({"p1"}), 3: frozenset({"p2"}), 4: frozenset()}),
        2026,
        "test",
        "synthetic alert",
        "test",
        "test",
    )
    assert [(a.from_member_id, a.to_member_id) for a in proposal.assets] == [(2, 3), (3, 2)]
