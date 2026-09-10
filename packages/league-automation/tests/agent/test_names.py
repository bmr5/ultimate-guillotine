"""Names resolve in the tools, deterministically, or say why they cannot."""

import pytest

from ultimate_guillotine.agent.tools.fixture import fixture_snapshot
from ultimate_guillotine.agent.tools.names import (
    Ambiguous,
    PlayerInfo,
    Unknown,
    resolve_member,
    resolve_player,
)
from ultimate_guillotine.trades.models import MemberRef

SNAPSHOT = fixture_snapshot()
MEMBERS = [
    MemberRef(2, "Member02", ("maxy", "max power"), nickname="Max", sleeper_display_name="mp99"),
    MemberRef(3, "Member03", ("max",), nickname="Maxwell"),
]
PLAYERS = {
    "p05b0": PlayerInfo("p05b0", "Bench 05-0", "RB", "FIX", "Out"),
    "fa1": PlayerInfo("fa1", "Free Agent One", "RB", "FIX", None),
    "dup1": PlayerInfo("dup1", "Josh Allen", "QB", "BUF", None),
    "dup2": PlayerInfo("dup2", "Josh Allen", "WR", "JAX", None),
}


def test_a_member_resolves_by_label_alias_nickname_team_name_or_join_key() -> None:
    assert resolve_member("member02", SNAPSHOT, MEMBERS).member_id == 2
    assert resolve_member("MAX POWER", SNAPSHOT, MEMBERS).member_id == 2
    assert resolve_member("mp99", SNAPSHOT, MEMBERS).member_id == 2
    assert resolve_member("Team 02", SNAPSHOT, MEMBERS).member_id == 2
    assert resolve_member("Maxwell", SNAPSHOT, MEMBERS).member_id == 3


def test_a_name_two_members_answer_to_is_ambiguous_and_lists_both() -> None:
    with pytest.raises(Ambiguous) as caught:
        resolve_member("max", SNAPSHOT, [MEMBERS[0], MemberRef(3, "Member03", ("max",))])
    assert caught.value.candidates == ["Member02", "Member03"]


def test_an_unknown_member_lists_the_league() -> None:
    with pytest.raises(Unknown) as caught:
        resolve_member("nobody", SNAPSHOT, MEMBERS)
    assert "Member01" in caught.value.hint and "Member18" in caught.value.hint


def test_a_player_resolves_exactly_by_last_name_or_from_the_roster() -> None:
    assert resolve_player("Bench 05-0", SNAPSHOT, PLAYERS).sleeper_player_id == "p05b0"
    assert resolve_player("Starter 07-3", SNAPSHOT, PLAYERS).sleeper_player_id == "p07s3"
    assert resolve_player("free agent one", SNAPSHOT, PLAYERS).sleeper_player_id == "fa1"


def test_a_shared_player_name_is_ambiguous_unless_one_is_rostered() -> None:
    with pytest.raises(Ambiguous) as caught:
        resolve_player("Josh Allen", SNAPSHOT, PLAYERS)
    assert len(caught.value.candidates) == 2
    rostered = dict(PLAYERS)
    rostered["p01s0"] = PlayerInfo("p01s0", "Josh Allen", "QB", "BUF", None)
    assert resolve_player("Josh Allen", SNAPSHOT, rostered).sleeper_player_id == "p01s0"


def test_an_unknown_player_says_so() -> None:
    with pytest.raises(Unknown):
        resolve_player("Nobody Nowhere", SNAPSHOT, PLAYERS)


def test_a_surname_shared_by_two_players_is_ambiguous_and_marks_the_rostered_one() -> None:
    allens = {
        "p01s0": PlayerInfo("p01s0", "Josh Allen", "QB", "BUF", None),
        "ka": PlayerInfo("ka", "Keenan Allen", "WR", "CHI", None),
    }
    with pytest.raises(Ambiguous) as caught:
        resolve_player("Allen", SNAPSHOT, allens)
    assert caught.value.candidates == [
        "Josh Allen (QB, BUF, on Member01's roster)",
        "Keenan Allen (WR, CHI, free agent)",
    ]


def test_a_surname_with_many_matches_lists_eight_and_counts_the_rest() -> None:
    allens = {
        f"a{n}": PlayerInfo(f"a{n}", f"Player{n} Allen", "WR", "FIX", None) for n in range(9)
    }
    with pytest.raises(Ambiguous) as caught:
        resolve_player("allen", SNAPSHOT, allens)
    assert len(caught.value.candidates) == 8
    assert "and 1 more" in str(caught.value)
