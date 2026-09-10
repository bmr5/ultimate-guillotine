"""The first four tools, over the fixture league. Every result carries its age."""

from datetime import timedelta

from ultimate_guillotine.advisor.fixture import ELIMINATED_MEMBER_ID, FIXTURE_SYNCED_AT
from ultimate_guillotine.agent.tools.league import (
    league_overview,
    player,
    projections,
    roster,
)
from ultimate_guillotine.agent.tools.source import FixtureSource

SOURCE = FixtureSource()
NOW = FIXTURE_SYNCED_AT + timedelta(minutes=7)


def _no_private_keys(result: dict) -> None:
    text = str(result)
    assert "display_name" not in text and "sender_hash" not in text and "chat_guid" not in text


def test_the_overview_ranks_the_board_and_stamps_its_age() -> None:
    result = league_overview(SOURCE, now=NOW)
    assert result["season"] == 2026 and result["week"] == 6
    assert result["age_minutes"] == 7 and result["as_of"].startswith("2026-10-08T15:00")
    teams = result["teams"]
    assert len(teams) == 18
    lowest = min((t for t in teams if not t["eliminated"]), key=lambda t: t["projected"])
    assert lowest["board_rank"] == 1 and lowest["member"] == "Member18"
    eliminated = next(t for t in teams if t["member"] == f"Member{ELIMINATED_MEMBER_ID}")
    assert eliminated["eliminated"] and eliminated["board_rank"] is None
    assert teams[0]["faab_remaining"] == 960
    _no_private_keys(result)


def test_a_roster_lists_holdings_with_injury_and_projections() -> None:
    result = roster(SOURCE, "Member05", weeks_ahead=1, now=NOW)
    assert result["member"] == "Member05"
    injured = next(h for h in result["holdings"] if h["player_id"] == "p05b0")
    assert injured["injury_status"] == "Out" and injured["slot"] == "bench"
    assert set(injured["projections"]) == {6, 7}
    assert result["weeks"] == [6, 7]
    _no_private_keys(result)


def test_an_unknown_or_ambiguous_member_comes_back_as_an_error() -> None:
    assert "No match" in roster(SOURCE, "Nobody", now=NOW)["error"]


def test_a_player_says_who_holds_them_or_that_nobody_does() -> None:
    held = player(SOURCE, "Starter 07-3", now=NOW)
    assert held["holder"] == "Member07" and held["slot"] == "starter"
    free = player(SOURCE, "Free Agent One", now=NOW)
    assert free["holder"] == "free agent" and free["injury_status"] is None


def test_projections_compare_named_members_or_rank_the_league() -> None:
    compared = projections(SOURCE, ["Member02", "Member03"], now=NOW)
    assert [row["member"] for row in compared["rows"]] == ["Member02", "Member03"]
    assert compared["rows"][0]["projected"] > compared["rows"][1]["projected"]
    board = projections(SOURCE, now=NOW)
    assert board["rows"][0]["member"] == "Member01" and board["rows"][-1]["board_rank"] == 1
    assert len(board["rows"]) == 17
