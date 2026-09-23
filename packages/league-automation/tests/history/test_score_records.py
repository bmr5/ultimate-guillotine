from decimal import Decimal

import pytest

from ultimate_guillotine.history.score_records import competitive_scores, saved_matchup_roster


def matchup(roster=1, points=100, starters=None, **extra):
    return {
        "roster_id": roster,
        "points": points,
        "starters": starters if starters is not None else [str(i) for i in range(1, 10)],
        "players_points": {},
        **extra,
    }


def test_cleared_roster_never_returns_to_records_after_receiving_a_keeper():
    rows, excluded = competitive_scores(
        {
            1: [matchup()],
            2: [matchup(points=0, starters=["0"] * 9)],
            3: [matchup(points=1.8, starters=["keeper"] + ["0"] * 8)],
        }
    )
    assert len(rows) == 1
    assert excluded == {1: 2}


def test_retired_player_placeholders_do_not_count_as_zero_score_records():
    rows, excluded = competitive_scores(
        {
            1: [matchup()],
            2: [matchup(points=0, starters=["retired"] * 5 + ["0"] * 4)],
            3: [matchup(points=30)],
        }
    )
    assert len(rows) == 1
    assert excluded == {1: 2}


def test_real_low_scores_partial_active_lineups_zero_and_overrides_are_kept():
    rows, excluded = competitive_scores(
        {
            1: [
                matchup(1, 22.5, ["0", "0"] + [str(i) for i in range(1, 8)]),
                matchup(2, 0),
                matchup(3, 100, custom_points=0),
                matchup(4, 158.6199951171875),
            ]
        }
    )
    assert [r["points"] for r in rows] == [
        Decimal("22.50"),
        Decimal(0),
        Decimal(0),
        Decimal("158.62"),
    ]
    assert excluded == {}


def test_duplicate_or_missing_weeks_refuse_import():
    with pytest.raises(ValueError, match="Duplicate"):
        competitive_scores({1: [matchup(), matchup()]})
    with pytest.raises(ValueError, match="Missing"):
        competitive_scores({1: []})


def test_full_lineup_counts_require_every_slot_and_distinct_players():
    rows, _ = competitive_scores(
        {
            1: [
                matchup(1, 22.5, ["0", "0"] + [str(i) for i in range(1, 8)]),
                matchup(2, 44.86),
                matchup(3, 0),  # Filled slots qualify even when every player scores zero.
                matchup(4, 50, [str(i) for i in range(1, 9)]),
                matchup(5, 60, ["1"] * 9),
            ]
        },
        required_starters=9,
    )
    assert [r["filled_starting_slots"] for r in rows] == [7, 9, 9, 8, 1]
    assert [r["filled_starting_slots"] == r["required_starters"] for r in rows] == [
        False,
        True,
        True,
        False,
        False,
    ]


def test_unknown_required_slots_are_not_guessed_from_a_short_lineup():
    rows, _ = competitive_scores({1: [matchup(starters=["1", "2", "3"])]})
    assert rows[0]["required_starters"] is None


def test_saved_roster_preserves_slots_bench_zero_and_missing_points():
    row = {
        "starters": ["0", "a", "b"],
        "starters_points": [0, 12.345, 0],
        "players": ["a", "b", "bench", "unknown"],
        "players_points": {"a": 99, "b": 0, "bench": 40},
        "private_field": "never copy",
    }
    directory = {
        "a": {"full_name": "Player A", "position": "RB"},
        "b": {"full_name": "Player B", "position": "WR"},
    }
    roster = saved_matchup_roster(row, ["QB", "RB", "WR", "BN"], directory)
    assert roster["starters"][0] == {
        "player_id": None,
        "player_label": "Empty slot",
        "position": None,
        "slot": "QB",
        "points": 0,
    }
    assert [p["points"] for p in roster["starters"]] == [0, 12.35, 0]
    assert [p["player_id"] for p in roster["bench"]] == ["bench", "unknown"]
    assert roster["bench"][1]["points"] is None
    assert "private_field" not in str(roster)


def test_saved_roster_falls_back_to_player_points_and_rejects_extra_slots():
    row = {"starters": ["a"], "players_points": {"a": -1}}
    roster = saved_matchup_roster(row, ["QB", "WR"], {})
    assert roster["starters"][0]["points"] == -1
    assert roster["starters"][1]["player_id"] is None
    with pytest.raises(ValueError, match="more starters"):
        saved_matchup_roster({"starters": ["a", "b"]}, ["QB"], {})
