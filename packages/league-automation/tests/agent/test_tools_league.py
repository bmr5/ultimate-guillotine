"""The tools, over the fixture league. Every snapshot-backed result carries its age."""

from datetime import timedelta, timezone

from ultimate_guillotine.advisor.fixture import ELIMINATED_MEMBER_ID, FIXTURE_SYNCED_AT
from ultimate_guillotine.agent.tools.league import (
    history,
    league_overview,
    player,
    price_history,
    projections,
    roster,
    rules,
    survival,
    trade_math,
    trades,
    transactions,
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


def test_the_stamp_dates_the_oldest_sync_in_utc_and_shows_the_newest() -> None:
    eastern = timezone(timedelta(hours=-4))
    older = (FIXTURE_SYNCED_AT - timedelta(minutes=30)).astimezone(eastern)
    result = league_overview(FixtureSource(oldest_synced_at=older), now=NOW)
    assert result["as_of"] == "2026-10-08T14:30:00+00:00"
    assert result["newest_sync"] == "2026-10-08T15:00:00+00:00"
    assert result["age_minutes"] == 37


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


def test_trades_render_terms_by_label_and_never_the_excerpt() -> None:
    class Traded(FixtureSource):
        def trades(self, seasons):
            return [{
                "trade_code": "T-2026-001", "season": 2026,
                "terms": {
                    "kind": "rental", "effective_week": 4,
                    "assets": [
                        {"kind": "player", "from_member_id": 1, "to_member_id": 2,
                         "player_id": "p01b0", "player_name": "Bench 01-0", "amount": None,
                         "unit": None, "description": None},
                        {"kind": "faab", "from_member_id": 2, "to_member_id": 1,
                         "player_id": None, "player_name": None, "amount": 80,
                         "unit": "faab", "description": None},
                    ],
                    "parties": [], "special_terms": ["returns before the Week 7 lock"],
                    "evidence_excerpt": "NEVER SHOWN",
                },
            }]

    result = trades(Traded(), member="Member02", now=NOW)
    assert result["trades"][0]["code"] == "T-2026-001"
    assert result["trades"][0]["assets"][0] == {
        "kind": "player", "player": "Bench 01-0", "player_id": "p01b0", "position": "RB",
        "amount": None, "unit": None, "from": "Member01", "to": "Member02",
    }
    assert "NEVER SHOWN" not in str(result)
    _no_private_keys(result)
    assert trades(Traded(), member="Member09", now=NOW)["trades"] == []


def test_price_history_quotes_what_the_league_paid() -> None:
    from tests.advisor.fixture import PERMANENT_ROW, RENTAL_ROW

    class Priced(FixtureSource):
        def trades(self, seasons):
            return [PERMANENT_ROW, RENTAL_ROW]

    result = price_history(Priced(), "RB", now=NOW)
    assert result["median_faab"] == 80 and result["comparables"][0]["code"] == "T-2026-001"
    rental = price_history(Priced(), "RB", kind="rental", now=NOW)
    assert rental["median_faab"] == 30
    assert price_history(Priced(), "TE", now=NOW)["comparables"] == []


def test_trade_math_values_each_side_and_flags_the_impossible() -> None:
    legs = [
        {"kind": "player", "player": "Bench 02-0", "from": "Member02", "to": "Member18"},
        {"kind": "faab", "amount": 40, "from": "Member18", "to": "Member02"},
    ]
    result = trade_math(SOURCE, legs, now=NOW)
    assert result["flags"] == []
    assert result["projections_complete"] is True
    sides = result["sides"]
    assert sides["Member18"]["faab_after"] == (1000 - 40 * 18) - 40
    assert sides["Member02"]["faab_after"] == (1000 - 40 * 2) + 40
    assert isinstance(sides["Member18"]["lineup_delta"], float)
    assert sides["Member02"]["lineup_delta"] == 0.0
    _no_private_keys(result)
    bad = trade_math(SOURCE, [
        {"kind": "player", "player": "Bench 02-0", "from": "Member03", "to": "Member18"},
        {"kind": "faab", "amount": 5000, "from": "Member18", "to": "Member03"},
        {"kind": "player", "player": "Bench 17-0", "from": "Member17", "to": "Member18"},
    ], now=NOW)
    assert any("not on Member03" in flag for flag in bad["flags"])
    assert any("over" in flag and "budget" in flag for flag in bad["flags"])
    assert any("eliminated" in flag for flag in bad["flags"])


def test_rules_return_the_whole_file_or_one_topic() -> None:
    everything = rules(SOURCE)
    assert "Trading" in everything["rules"]
    section = rules(SOURCE, topic="waiver")
    assert "Waivers" in section["rules"] and "Shape of the league" not in section["rules"]


def test_history_lists_placings_and_survival_lists_the_week() -> None:
    seasons = history(SOURCE)
    assert [s["season"] for s in seasons["seasons"]] == [2024, 2025]
    assert seasons["seasons"][1]["champion"] == "Member09"
    one = history(SOURCE, season=2025)
    assert one["seasons"][0]["eliminations"][0]["member"] == "Member17"
    week = survival(SOURCE, now=NOW)
    assert week["week"] == 6 and week["scores"][0]["member"] == "Member18"
    assert week["eliminated"] == [{"member": "Member17", "week": 5, "source": "adjudicator"}]


def test_transactions_name_the_teams_and_players() -> None:
    result = transactions(SOURCE, now=NOW)
    move = result["transactions"][0]
    assert move["type"] == "free_agent" and move["week"] == 6
    assert move["moves"] == [{"member": "Member05", "adds": ["Free Agent One"],
                              "drops": ["Bench 05-5"]}]
