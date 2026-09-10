import pytest

from ultimate_guillotine.sleeper.models import SleeperRoster
from ultimate_guillotine.sleeper.players import Player
from ultimate_guillotine.trades.models import ExtractedAsset, ExtractedParty, ExtractedTrade
from ultimate_guillotine.trades.names import normalize_name
from ultimate_guillotine.trades.resolve import (
    _NFL_TEAMS,
    MemberRef,
    RosterIndex,
    Unresolved,
    _resolve_player_with_rosters,
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


NFL_DEF_ROWS = [
    Player(abbr, f"{words[0]} {words[1]}", "DEF", abbr, True)
    for abbr, words in _NFL_TEAMS.items()
]
#: The two cities `_build_defense_aliases` drops as shared: `Buffalo` names one
#: club, `Los Angeles` names two, so only the nickname and the pair are checked.
SHARED_CITIES = {"Los Angeles", "New York"}


@pytest.mark.parametrize("abbr", list(_NFL_TEAMS), ids=list(_NFL_TEAMS))
def test_every_club_resolves_by_abbreviation_city_and_nickname(abbr: str) -> None:
    """Every row of `_NFL_TEAMS` has to reach its own `DEF` row three ways --
    a typo in one club's entry would otherwise only surface in the chat."""
    city, nickname = _NFL_TEAMS[abbr][0], _NFL_TEAMS[abbr][1]
    typings = [abbr, f"{city} {nickname}", nickname, f"the {nickname} D/ST"]
    if city not in SHARED_CITIES:
        typings.append(city)
    for typed in typings:
        proposal = resolve_with(NFL_DEF_ROWS, extracted(assets=[player_asset(typed)]))
        assert proposal.assets[0].player_id == abbr, typed


@pytest.mark.parametrize(
    "name", ["Washington Football Team", "Football Team", "WFT", "the WFT D", "Commanders"]
)
def test_washington_resolves_under_the_name_it_used_to_have(name: str) -> None:
    """Half the league still types the old name, and the `DEF` row is filed
    under `WAS` whichever name is typed."""
    proposal = resolve_with(NFL_DEF_ROWS, extracted(assets=[player_asset(name)]))
    assert proposal.assets[0].player_id == "WAS"


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


FATHER = Player("p11", "Marvin Harrison", "WR", "IND", True)


def test_a_father_and_son_both_on_file_make_the_bare_name_ambiguous() -> None:
    """`Marvin Harrison` with both generations on file names either of them.
    Matching the row spelled without the suffix would be a guess, and a guess
    logs the wrong player, so the chat is asked which one."""
    with pytest.raises(Unresolved) as info:
        resolve_with(
            [*PLAYERS, HARRISON, FATHER], extracted(assets=[player_asset("Marvin Harrison")])
        )
    assert info.value.reason == "Two players named Marvin Harrison; which one?"


def test_the_suffix_picks_the_son_when_both_are_on_file() -> None:
    """The suffix is the only thing that separates them, so a spelling that
    carries it and matches a row exactly still resolves on its own."""
    proposal = resolve_with(
        [*PLAYERS, HARRISON, FATHER], extracted(assets=[player_asset("Marvin Harrison Jr.")])
    )
    assert proposal.assets[0].player_id == "p9"


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


#: A first-person party name, as the model would leave it if it ignored the
#: prompt's instruction to write the announcer's username instead.
FIRST_PERSON = ("me", "Me", "I", "my team", "My Team", "myself")


@pytest.mark.parametrize("pronoun", FIRST_PERSON, ids=FIRST_PERSON)
def test_a_first_person_party_resolves_to_the_announcer(pronoun: str) -> None:
    """The prompt asks for the username; this is the guard for when the model
    writes the pronoun through anyway, so the trade is still logged."""
    e = extracted(
        parties=[ExtractedParty(name=pronoun), ExtractedParty(name="Member02")],
        assets=[
            ExtractedAsset(kind="player", from_party=pronoun, to_party="Member02",
                           player_name="Player Alpha", amount=None, unit=None, description=None),
        ],
    )
    proposal = resolve_extracted(
        e, MEMBERS, PLAYERS, ROSTERS, 2026, "g1", "x", "2026.1", "m", announcer=MEMBERS[0]
    )
    assert [p.member_id for p in proposal.parties] == [1, 2]
    assert proposal.assets[0].from_member_id == 1 and proposal.assets[0].to_member_id == 2


def test_a_first_person_party_with_no_announcer_asks_the_chat() -> None:
    """No announcer means the sender was never placed -- an unloaded handle -- so
    `me` is a name nobody has, and the wording is the one it always was."""
    e = extracted(parties=[ExtractedParty(name="me"), ExtractedParty(name="Member02")])
    with pytest.raises(Unresolved) as info:
        resolve_extracted(e, MEMBERS, PLAYERS, ROSTERS, 2026, "g1", "x", "2026.1", "m")
    assert info.value.reason == "I don't recognize 'me' as a league member"


def test_a_member_who_goes_by_a_first_person_word_keeps_their_name() -> None:
    """The member index is asked before the pronoun guard: an alias really is a
    name, and the announcer only stands in for a word nobody answers to."""
    members = [*MEMBERS, MemberRef(5, "Member05", ("me",))]
    e = extracted(parties=[ExtractedParty(name="me"), ExtractedParty(name="Member02")],
                  assets=[ExtractedAsset(kind="player", from_party="me", to_party="Member02",
                                         player_name="Player Alpha", amount=None, unit=None,
                                         description=None)])
    proposal = resolve_extracted(
        e, members, PLAYERS, ROSTERS, 2026, "g1", "x", "2026.1", "m", announcer=MEMBERS[0]
    )
    assert [p.member_id for p in proposal.parties] == [5, 2]


def test_the_announcer_is_not_added_to_a_trade_that_never_mentions_them() -> None:
    """Knowing who posted an alert is not a reason to make them a party to it:
    a member relaying two other people's trade stays out of the record."""
    proposal = resolve_extracted(
        extracted(), MEMBERS, PLAYERS, ROSTERS, 2026, "g1", "x", "2026.1", "m",
        announcer=MEMBERS[3],
    )
    assert [p.member_id for p in proposal.parties] == [1, 2]


# -- partial player names resolved against the parties' rosters ---------------
#
# The real message: "Derek sends a 1 week Rhamondre rental to Charlie". A first
# name is not an exact match, is not a surname, and is not a defense, so the old
# chain answered "I can't find a player named Rhamondre" about a man sitting on
# Derek's roster. These names are synthetic and deliberately unlike anyone's.

ROSTER_PLAYERS = [
    *PLAYERS,
    Player("p10", "Rashaan Bellwether", "RB", "NE", True),
    Player("p11", "Michael Bellwether", "RB", "DAL", True),
    Player("p12", "Michael Tolliver", "WR", "ARI", True),
    Player("p13", "Gavin Tolliver", "TE", "SEA", True),
    Player("p14", "Van Quillon", "WR", "LAR", True),
    Player("p15", "Sam Fernsby", "QB", "GB", True),
]
#: Member01 gives; Member02 receives. `Sam Fernsby` is on nobody's roster, which
#: is what a free agent or an unsynced team looks like from here.
ROSTERED = RosterIndex(
    {
        1: frozenset({"p1", "p10", "p11", "p12", "p14"}),
        2: frozenset({"p13"}),
        3: frozenset(),
    }
)


def rostered(name: str):
    """Resolve one player asset given away by Member01, against the rosters above."""
    e = extracted(assets=[player_asset(name)])
    return resolve_extracted(
        e, MEMBERS, ROSTER_PLAYERS, ROSTERED, 2026, "g1", "x", "2026.1", "m"
    )


def test_a_first_name_resolves_against_the_giving_party_s_roster() -> None:
    """The message that started this: a rental announced by first name only."""
    proposal = rostered("Rashaan")
    assert proposal.assets[0].player_id == "p10"


def test_a_surname_two_men_share_is_settled_by_whose_roster_he_is_on() -> None:
    """Both Tollivers are rostered, so the old surname rule over every active
    player would ask which team. The giver has only one of them."""
    assert rostered("Tolliver").assets[0].player_id == "p12"


def test_a_name_on_nobody_else_s_roster_resolves_league_wide() -> None:
    """A giver who has already dropped him, or a name typed for the receiving
    side: the league's rosters are still a far smaller haystack than the
    directory, and one match in them is an answer."""
    assert rostered("Gavin").assets[0].player_id == "p13"


def test_two_players_on_the_giver_s_roster_answer_to_the_name_so_the_chat_is_asked() -> None:
    """Roster evidence narrows; it never guesses. Both Bellwethers are the
    giver's, so this is a question rather than a coin toss."""
    with pytest.raises(Unresolved) as info:
        rostered("Bellwether")
    assert info.value.reason == "Two players named Bellwether on that roster; which one?"


def test_a_name_nobody_in_the_league_answers_to_keeps_the_old_message() -> None:
    with pytest.raises(Unresolved) as info:
        rostered("Nonexistent Placeholder")
    assert info.value.reason == "I can't find a player named Nonexistent Placeholder"


def test_a_full_typed_name_is_never_swapped_for_a_different_rostered_one() -> None:
    """`Justin Quillon` is not in the directory and `Van Quillon` is, on the
    giver's roster. Sharing a surname is not being the same man, so this asks
    rather than recording a trade for somebody nobody named."""
    with pytest.raises(Unresolved) as info:
        rostered("Justin Quillon")
    assert info.value.reason == "I can't find a player named Justin Quillon"


def test_an_exact_name_still_wins_before_any_roster_is_read() -> None:
    assert (
        rostered("Michael Tolliver").assets[0].player_id == "p12"
    )


def test_an_asset_with_no_giver_falls_back_to_the_old_chain() -> None:
    """Nothing says whose roster to read, so the giver's-roster step is skipped
    and a bare surname is answered the way it was before rosters were consulted
    -- `Sam Fernsby` is on nobody's roster at all."""
    assert (
        _resolve_player_with_rosters("Fernsby", ROSTER_PLAYERS, ROSTERED, None) == "p15"
    )


def test_an_empty_roster_index_leaves_resolution_exactly_as_it_was() -> None:
    """A Sleeper outage or a database-less dry run loses roster evidence and must
    degrade to the old answers rather than to no answers."""
    assert (
        _resolve_player_with_rosters("Fernsby", ROSTER_PLAYERS, RosterIndex.empty(), 1) == "p15"
    )
    with pytest.raises(Unresolved) as info:
        _resolve_player_with_rosters("Rashaan", ROSTER_PLAYERS, RosterIndex.empty(), 1)
    assert info.value.reason == "I can't find a player named Rashaan"


def test_all_players_is_every_roster_folded_together() -> None:
    assert ROSTERED.all_players() == frozenset({"p1", "p10", "p11", "p12", "p13", "p14"})
    assert RosterIndex.empty().all_players() == frozenset()
    assert ROSTERED.players_for(None) == frozenset()
    assert ROSTERED.players_for(99) == frozenset()


def test_an_unknown_member_is_asked_about_before_an_unfindable_player() -> None:
    """Two things wrong, one question: the chat is asked about the member.

    Player names are resolved twice and the answer that gets reported comes from
    the second pass, which runs *after* the parties -- so an announcement naming
    both a stranger and a player nobody has heard of ends in the member question,
    not the player one. Nothing depends on which of the two is asked, but the
    order is a behaviour rather than an accident, and a change to it should have
    to edit this test rather than surprise somebody reading the chat.
    """
    with pytest.raises(Unresolved) as info:
        resolve(
            extracted(
                parties=[ExtractedParty(name="Nobody"), ExtractedParty(name="Member02")],
                assets=[player_asset("Nobody Here", from_party="Nobody")],
            )
        )
    assert info.value.reason == "I don't recognize 'Nobody' as a league member"


def faab_asset(
    amount: int,
    currency: str = "faab",
    from_party: str = "Member02",
    to_party: str = "member01",
    description: str | None = None,
) -> ExtractedAsset:
    return ExtractedAsset(
        kind="faab", from_party=from_party, to_party=to_party, player_name=None,
        amount=amount, unit="faab", currency=currency, description=description,
    )


def test_a_price_quoted_in_draft_dollars_is_recorded_as_faab() -> None:
    """The league's own rule: every $1 of unspent draft budget became $5 of FAAB.
    So `$13 draft` is 65 FAAB, and 13 sitting in a FAAB column would read as a
    fifth of what was paid."""
    proposal = resolve(extracted(assets=[faab_asset(13, currency="draft")]))
    money = proposal.assets[0]
    assert money.amount == 65
    assert money.unit == "faab" and money.kind == "faab"


def test_an_amount_already_converted_is_not_converted_again() -> None:
    """The prompt asks the model to do the arithmetic and keep the announcement's
    own phrase in the label. When it does, the guard has to stay out of the way --
    `$65 FAAB ($13 draft)` is 65, never 325."""
    proposal = resolve(
        extracted(assets=[faab_asset(65, description="$65 FAAB ($13 draft FAAB)")])
    )
    money = proposal.assets[0]
    assert money.amount == 65
    assert money.description == "$65 FAAB ($13 draft FAAB)"


def test_a_price_written_twice_is_recorded_once() -> None:
    """The plainest thing a model can do with `$65 FAAB ($13 draft)` is write two
    assets, and two FAAB assets on one leg are added up -- so the trade would be
    logged as 130 FAAB paid. They are the same money, so one of them is kept: the
    one already written in FAAB, whose description carries the alert's words."""
    proposal = resolve(
        extracted(
            assets=[
                faab_asset(65, description="$65 FAAB"),
                faab_asset(13, currency="draft", description="$13 draft FAAB"),
            ]
        )
    )
    assert [(a.amount, a.description) for a in proposal.assets] == [(65, "$65 FAAB")]


def test_two_prices_that_disagree_are_a_question_for_the_chat() -> None:
    """`$70 FAAB ($13 draft)` is 70 and 65: the announcement states two different
    prices and nothing here can pick between them."""
    with pytest.raises(Unresolved) as info:
        resolve(
            extracted(
                assets=[faab_asset(70), faab_asset(13, currency="draft")]
            )
        )
    assert info.value.reason == "That says 65, 70 FAAB for the same thing; which is it?"


def test_the_model_flagging_disagreeing_prices_reaches_the_chat_as_its_reason() -> None:
    """The prompt asks the model to answer `unclear` when the two amounts do not
    agree, and its sentence is what the chat is asked."""
    with pytest.raises(Unresolved) as info:
        resolve(
            extracted(
                kind="unclear",
                unclear_reason="65 FAAB and 13 draft dollars are different amounts",
            )
        )
    assert info.value.reason == "65 FAAB and 13 draft dollars are different amounts"


def test_two_separate_faab_payments_on_one_leg_are_left_alone() -> None:
    """`50 FAAB now and 50 more after Week 4` is two payments, not one written
    twice, and collapsing it would silently halve what was paid. Only a leg with
    a draft quote on it is reconciled at all."""
    proposal = resolve(
        extracted(assets=[faab_asset(50, description="now"), faab_asset(50, description="later")])
    )
    assert [a.amount for a in proposal.assets] == [50, 50]


def test_real_money_is_never_multiplied() -> None:
    """`usd` is neither of the league's budgets: $13 cash is $13."""
    proposal = resolve(
        extracted(
            assets=[
                ExtractedAsset(
                    kind="usd", from_party="Member02", to_party="member01", player_name=None,
                    amount=13, unit="usd", currency="draft", description=None,
                )
            ]
        )
    )
    assert proposal.assets[0].amount == 13 and proposal.assets[0].unit == "usd"


def test_an_asset_with_no_currency_stated_is_faab_as_it_always_was() -> None:
    """The field defaults, so nothing that predates it changes."""
    assert ExtractedAsset(kind="faab", amount=100, unit="faab").currency == "faab"
    proposal = resolve(extracted())
    assert proposal.assets[1].amount == 450
