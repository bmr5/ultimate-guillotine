import pytest

from ultimate_guillotine.sleeper.models import SleeperRoster
from ultimate_guillotine.sleeper.players import Player
from ultimate_guillotine.trades.models import ExtractedAsset, ExtractedParty, ExtractedTrade
from ultimate_guillotine.trades.names import normalize_name
from ultimate_guillotine.trades.resolve import (
    MemberRef,
    RosterIndex,
    Unresolved,
    build_roster_index,
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
    Player("BUF", "Buffalo Bills", "DEF", "BUF", True),
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


def resolve_with(players: list[Player], e: ExtractedTrade):
    return resolve_extracted(e, MEMBERS, players, ROSTERS, 2026, "g1", "x", "2026.1", "m")


def player_asset(
    name: str, from_party: str = "member01", to_party: str = "Member02"
) -> ExtractedAsset:
    return ExtractedAsset(
        kind="player", from_party=from_party, to_party=to_party, player_name=name,
        amount=None, unit=None, description=None,
    )


HARRISON = Player("p9", "Marvin Harrison Jr.", "WR", "ARI", True)


def test_last_name_match_ignores_a_generational_suffix() -> None:
    proposal = resolve_with([*PLAYERS, HARRISON], extracted(assets=[player_asset("Harrison")]))
    assert proposal.assets[0].player_id == "p9"


def test_a_bare_suffix_matches_no_player() -> None:
    with pytest.raises(Unresolved) as info:
        resolve_with([*PLAYERS, HARRISON], extracted(assets=[player_asset("III")]))
    assert info.value.reason == "I can't find a player named III"


@pytest.mark.parametrize("name", ["Kansas City Chiefs", "KC D/ST", "KC DEF"])
def test_defense_resolves_by_full_name_or_team_code(name: str) -> None:
    assert resolve(extracted(assets=[player_asset(name)])).assets[0].player_id == "KC"


@pytest.mark.parametrize(
    "name",
    [
        "Buffalo Bills defense",
        "the Bills D/ST",
        "Bills DEF",
        "BUF",
        "buffalo bills",
        "the BUF D",
        "Buffalo",
    ],
)
def test_a_team_defense_resolves_however_it_was_typed(name: str) -> None:
    """City, nickname, both, or the abbreviation -- all one row."""
    assert resolve(extracted(assets=[player_asset(name)])).assets[0].player_id == "BUF"


def test_a_city_two_clubs_share_names_no_defense() -> None:
    """`the New York defense` names neither the Giants nor the Jets, so it asks."""
    with pytest.raises(Unresolved) as info:
        resolve(extracted(assets=[player_asset("the New York defense")]))
    assert info.value.reason == "I can't find a player named the New York defense"


WALKER = Player("p10", "Kenneth Walker III", "RB", "SEA", True)


@pytest.mark.parametrize(
    ("typed", "player_id"),
    [
        ("Marvin Harrison Jr.", "p9"),
        ("Marvin Harrison", "p9"),
        ("Kenneth Walker III", "p10"),
        ("Kenneth Walker", "p10"),
        ("Kenneth Walker Jr", "p10"),
    ],
)
def test_a_generational_suffix_matches_with_or_without_it(typed: str, player_id: str) -> None:
    """The directory and the chat rarely agree on the suffix; either spelling
    has to find the one row."""
    proposal = resolve_with([*PLAYERS, HARRISON, WALKER], extracted(assets=[player_asset(typed)]))
    assert proposal.assets[0].player_id == player_id


def test_an_exact_name_still_beats_a_suffix_insensitive_match() -> None:
    """Suffix-blind matching runs only after an exact match has failed, so a
    father and son both on file stay separate players."""
    father = Player("p11", "Marvin Harrison", "WR", "IND", True)
    proposal = resolve_with(
        [*PLAYERS, HARRISON, father], extracted(assets=[player_asset("Marvin Harrison")])
    )
    assert proposal.assets[0].player_id == "p11"


def test_unknown_player_name_is_unresolved() -> None:
    with pytest.raises(Unresolved) as info:
        resolve(extracted(assets=[player_asset("Nobody Here")]))
    assert info.value.reason == "I can't find a player named Nobody Here"


def test_four_members_sharing_an_alias_are_never_disambiguated() -> None:
    members = [MemberRef(i, f"Member0{i}", ("crew",)) for i in (1, 2, 3, 4)]
    e = extracted(
        parties=[ExtractedParty(name="crew"), ExtractedParty(name="Member02")],
        assets=[player_asset("Player Alpha", from_party="crew")],
    )
    with pytest.raises(Unresolved) as info:
        resolve_extracted(e, members, PLAYERS, ROSTERS, 2026, "g1", "x", "2026.1", "m")
    assert info.value.reason == "Two members go by 'crew'; which one?"


def test_receive_only_rule_settles_ambiguity_when_every_candidate_has_a_roster() -> None:
    # "nick" is Member01 and Member03; only Member03's roster lacks the incoming Player Alpha.
    e = extracted(
        parties=[ExtractedParty(name="Member02"), ExtractedParty(name="Nick")],
        assets=[player_asset("Player Alpha", from_party="Member02", to_party="Nick")],
    )
    assert [p.member_id for p in resolve(e).parties] == [2, 3]


def test_receive_only_rule_is_refused_when_a_candidate_has_no_roster_data() -> None:
    e = extracted(
        parties=[ExtractedParty(name="Member02"), ExtractedParty(name="Nick")],
        assets=[player_asset("Player Alpha", from_party="Member02", to_party="Nick")],
    )
    with pytest.raises(Unresolved) as info:
        resolve(e, RosterIndex({1: frozenset({"p1"}), 2: frozenset({"p2"})}))
    assert "which one" in info.value.reason


def test_non_player_asset_keeps_an_incidental_player_name_unresolved() -> None:
    e = extracted(assets=[ExtractedAsset(
        kind="faab", from_party="member01", to_party="Member02", player_name="Nobody Here",
        amount=10, unit="faab", description=None,
    )])
    asset = resolve(e).assets[0]
    assert asset.player_id is None
    assert asset.player_name == "Nobody Here"


def test_validate_rejects_an_amount_without_a_unit() -> None:
    # A money kind supplies its own unit; a player carrying a bare number does
    # not, and there is nothing to guess from.
    e = extracted(assets=[ExtractedAsset(
        kind="player", from_party="member01", to_party="Member02", player_name="player alpha",
        amount=10, unit=None, description=None,
    )])
    with pytest.raises(Unresolved) as info:
        validate(resolve(e))
    assert info.value.reason == "An amount needs a unit"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ｍike", "mike"),
        ("MEMBER01", "member01"),
        ("O'Neill-Jr.", "oneilljr"),
        ("member_01", "member01"),
        ("  two   words  ", "two words"),
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


class FakeRosterClient:
    """Serves a fixed roster list to ``build_roster_index``."""

    def __init__(self, rosters: list[SleeperRoster]) -> None:
        self._rosters = rosters

    def get_rosters(self, league_id: str) -> list[SleeperRoster]:
        return self._rosters


def test_build_roster_index_maps_members_to_their_holdings(conn) -> None:
    # build_roster_index reads the season it is handed, not the clock's year.
    year = 2031
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.members (display_name) values ('Roster Member') returning id"
        )
        member_id = cur.fetchone()[0]
        cur.execute(
            """
            insert into public.seasons (year, sleeper_league_id, rules_version)
            values (%s, 'league-1', 'v1')
            on conflict (year) do update set rules_version = excluded.rules_version
            returning id
            """,
            (year,),
        )
        season_id = cur.fetchone()[0]
        cur.execute(
            """
            insert into public.teams
                (season_id, member_id, sleeper_user_id, sleeper_roster_id, team_name)
            values (%s, %s, 'u', 7, 'Team Seven')
            """,
            (season_id, member_id),
        )

    client = FakeRosterClient([
        SleeperRoster(roster_id=7, owner_id="u", players=["p1"]),
        SleeperRoster(roster_id=71, owner_id="v", players=["p2"]),
        SleeperRoster(roster_id=72, owner_id="w", players=None),
    ])
    index = build_roster_index(client, conn, "league-1", year)
    assert index.holdings == {member_id: frozenset({"p1"})}
    assert index.holds(member_id, "p1") is True


def test_a_unit_wins_over_a_mislabelled_money_kind() -> None:
    """The model sometimes types the wrong money kind next to the right unit;
    the unit is the specific field, so it decides."""
    e = extracted(assets=[ExtractedAsset(
        kind="usd", from_party="member01", to_party="Member02", player_name=None,
        amount=25, unit="faab", description=None,
    )])
    asset = resolve(e).assets[0]
    assert asset.kind == "faab" and asset.unit == "faab" and asset.amount == 25


def test_a_money_kind_without_a_unit_becomes_its_own_unit() -> None:
    e = extracted(assets=[ExtractedAsset(
        kind="draft_dollars", from_party="member01", to_party="Member02", player_name=None,
        amount=30, unit=None, description=None,
    )])
    asset = resolve(e).assets[0]
    assert asset.kind == "draft_dollars" and asset.unit == "draft_dollars"


def test_a_non_money_asset_keeps_its_description_and_drops_the_amount() -> None:
    """`protection` and `other` are terms, not amounts: a bare `1` next to one
    would print as nonsense in the chat."""
    e = extracted(assets=[ExtractedAsset(
        kind="other", from_party="member01", to_party="Member02", player_name=None,
        amount=1, unit=None, description="one gulag pass",
    )])
    asset = resolve(e).assets[0]
    assert asset.kind == "other" and asset.amount is None
    assert asset.description == "one gulag pass"


def test_a_two_token_name_never_falls_back_to_the_last_name() -> None:
    """Someone typed a full name; matching it to a different player who happens
    to share the surname would log the wrong trade."""
    players = [Player("p9", "Van Jefferson", "WR", "PIT", True)]
    e = extracted(assets=[ExtractedAsset(
        kind="player", from_party="member01", to_party="Member02",
        player_name="Justin Jefferson", amount=None, unit=None, description=None,
    )])
    with pytest.raises(Unresolved) as info:
        resolve_extracted(e, MEMBERS, players, ROSTERS, 2026, "g1", "🚨 ...", "2026.1", "m")
    assert info.value.reason == "I can't find a player named Justin Jefferson"


def test_a_single_token_name_still_falls_back_to_the_last_name() -> None:
    players = [Player("p9", "Van Jefferson", "WR", "PIT", True)]
    e = extracted(assets=[ExtractedAsset(
        kind="player", from_party="member01", to_party="Member02",
        player_name="Jefferson", amount=None, unit=None, description=None,
    )])
    proposal = resolve_extracted(
        e, MEMBERS, players, ROSTERS, 2026, "g1", "🚨 ...", "2026.1", "m"
    )
    assert proposal.assets[0].player_id == "p9"
