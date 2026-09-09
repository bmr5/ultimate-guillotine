import json
from decimal import Decimal
from pathlib import Path

from ultimate_guillotine.sleeper.models import SleeperRoster
from ultimate_guillotine.sleeper.roster_state import (
    Elimination,
    bumps_state_version,
    classify_holdings,
    infer_elimination,
    merge_elimination,
    team_state_from_roster,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sleeper" / "rosters_2026.json"
POSITIONS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]


def rosters() -> list[SleeperRoster]:
    return [SleeperRoster.model_validate(r) for r in json.loads(FIXTURE.read_text())]


def test_slots_come_straight_from_the_sleeper_payload() -> None:
    result = classify_holdings(rosters()[0], POSITIONS)
    by_id = {h.sleeper_player_id: h for h in result.holdings}
    assert by_id["4034"].slot == "starter"
    assert by_id["10881"].slot == "ir"
    assert by_id["4943"].slot == "taxi"
    # 6794 is in the starters list, so it is a starter and not bench.
    assert by_id["6794"].slot == "starter"
    assert {h.slot for h in result.holdings} == {"starter", "ir", "taxi"}


def test_starter_index_and_lineup_position_come_from_roster_positions() -> None:
    by_id = {h.sleeper_player_id: h for h in classify_holdings(rosters()[0], POSITIONS).holdings}
    assert (by_id["4034"].slot_index, by_id["4034"].lineup_position) == (0, "QB")
    assert (by_id["9488"].slot_index, by_id["9488"].lineup_position) == (3, "WR")
    assert (by_id["SEA"].slot_index, by_id["SEA"].lineup_position) == (8, "DEF")
    assert by_id["10881"].slot_index is None and by_id["10881"].lineup_position is None


def test_a_blank_starter_slot_produces_no_row() -> None:
    result = classify_holdings(rosters()[0], POSITIONS)
    assert "0" not in {h.sleeper_player_id for h in result.holdings}
    assert len(result.holdings) == 9


def test_a_bench_only_roster_classifies_everything_bench() -> None:
    roster = SleeperRoster.model_validate(
        {"roster_id": 3, "owner_id": "u3", "players": ["a", "b"], "starters": []}
    )
    result = classify_holdings(roster, POSITIONS)
    assert [h.slot for h in result.holdings] == ["bench", "bench"]


def test_a_repeated_starter_id_keeps_its_first_slot() -> None:
    """Sleeper has been seen repeating an id across two starter slots; one row wins."""
    roster = SleeperRoster.model_validate(
        {"roster_id": 5, "owner_id": "u5", "players": ["a", "b"], "starters": ["a", "a", "b"]}
    )
    holdings = classify_holdings(roster, POSITIONS).holdings
    assert [h.sleeper_player_id for h in holdings] == ["a", "b"]
    assert [(h.slot, h.slot_index, h.lineup_position) for h in holdings] == [
        ("starter", 0, "QB"),
        ("starter", 2, "RB"),
    ]


def test_a_starter_missing_from_players_is_still_a_starter() -> None:
    """``starters`` is authoritative: an id Sleeper left out of ``players`` still starts."""
    roster = SleeperRoster.model_validate(
        {"roster_id": 6, "owner_id": "u6", "players": ["b"], "starters": ["ghost", "b"]}
    )
    holdings = classify_holdings(roster, POSITIONS).holdings
    assert [(h.sleeper_player_id, h.slot) for h in holdings] == [
        ("ghost", "starter"),
        ("b", "starter"),
    ]


def test_null_lists_and_dicts_become_empty() -> None:
    roster = rosters()[1]
    assert roster.starters == [] and roster.players == []
    assert roster.reserve == [] and roster.taxi == []
    assert classify_holdings(roster, POSITIONS).holdings == ()


def test_a_roster_with_no_settings_block_gets_an_empty_dict() -> None:
    roster = SleeperRoster.model_validate(
        {"roster_id": 4, "owner_id": "u4", "settings": None, "metadata": None}
    )
    assert roster.settings == {} and roster.metadata == {}


def test_faab_and_points_recombine_sleepers_split_integers() -> None:
    state = team_state_from_roster(rosters()[0], waiver_budget=1000)
    assert (state.faab_budget, state.faab_used) == (1000, 250)
    assert state.points_for == Decimal("312.45")
    assert state.points_against == Decimal("289.07")
    assert (state.wins, state.losses, state.ties) == (2, 1, 0)


def test_a_league_without_a_waiver_budget_records_zero_not_none() -> None:
    state = team_state_from_roster(rosters()[1], waiver_budget=None)
    assert (state.faab_budget, state.faab_used) == (0, 0)
    assert state.points_for == Decimal(0) and state.points_against == Decimal(0)


def test_points_keep_every_hundredth_a_float_payload_carries() -> None:
    """A float ``fpts`` already holds the fraction; truncating it would lose it."""
    roster = SleeperRoster.model_validate(
        {"roster_id": 7, "owner_id": "u7", "settings": {"fpts": 312.45}}
    )
    assert team_state_from_roster(roster, waiver_budget=0).points_for == Decimal("312.45")


def test_hundredths_take_the_sign_of_a_negative_whole_part() -> None:
    roster = SleeperRoster.model_validate(
        {
            "roster_id": 8,
            "owner_id": "u8",
            "settings": {"fpts_against": -12, "fpts_against_decimal": 5},
        }
    )
    assert team_state_from_roster(roster, waiver_budget=0).points_against == Decimal("-12.05")


def test_faab_spent_never_exceeds_the_budget() -> None:
    """Remaining FAAB is budget minus used, so used above budget would go negative."""
    spender = SleeperRoster.model_validate(
        {"roster_id": 9, "owner_id": "u9", "settings": {"waiver_budget_used": 250}}
    )
    for budget in (None, 0):
        state = team_state_from_roster(spender, waiver_budget=budget)
        assert (state.faab_budget, state.faab_used) == (0, 0)
        assert state.faab_budget - state.faab_used == 0
    overspent = SleeperRoster.model_validate(
        {"roster_id": 10, "owner_id": "u10", "settings": {"waiver_budget_used": 1200}}
    )
    state = team_state_from_roster(overspent, waiver_budget=1000)
    assert (state.faab_budget, state.faab_used) == (1000, 1000)
    assert state.faab_budget - state.faab_used == 0


def test_inference_reads_only_bens_metadata_tag() -> None:
    assert infer_elimination(rosters()[0], week=3) == Elimination.none()
    inferred = infer_elimination(rosters()[1], week=3)
    assert inferred == Elimination(True, 3, "sleeper_inferred")


def test_inferred_never_overwrites_adjudicated() -> None:
    ruled = Elimination(True, 2, "adjudicator")
    assert merge_elimination(ruled, Elimination(False, None, "sleeper_inferred")) == ruled
    assert merge_elimination(ruled, Elimination(True, 5, "sleeper_inferred")) == ruled
    # Manual outranks inference too, and the Adjudicator outranks everything.
    manual = Elimination(True, 4, "manual")
    assert merge_elimination(manual, Elimination(True, 6, "sleeper_inferred")) == manual
    assert merge_elimination(manual, ruled) == ruled
    assert merge_elimination(None, Elimination(True, 3, "sleeper_inferred")).is_eliminated


def test_an_unknown_stored_source_loses_precedence_instead_of_raising() -> None:
    stored = Elimination(True, 2, "imported_from_2025")
    incoming = Elimination(True, 5, "sleeper_inferred")
    assert merge_elimination(stored, incoming) == incoming


def test_clearing_the_sleeper_tag_never_un_eliminates_an_inferred_record() -> None:
    """Elimination is one-way for inference; only manual or adjudicator can reverse it."""
    stored = Elimination(True, 3, "sleeper_inferred")
    assert merge_elimination(stored, Elimination.none()) == stored
    assert merge_elimination(stored, infer_elimination(rosters()[0], week=4)) == stored
    reversed_by_hand = Elimination(False, None, "manual")
    assert merge_elimination(stored, reversed_by_hand) == reversed_by_hand


def test_state_version_bumps_only_on_an_actual_elimination_change() -> None:
    stored = Elimination(False, None, None)
    assert not bumps_state_version(stored, Elimination(False, None, "sleeper_inferred"))
    assert bumps_state_version(stored, Elimination(True, 3, "sleeper_inferred"))
    assert bumps_state_version(Elimination(True, 3, "adjudicator"),
                               Elimination(True, 4, "adjudicator"))
    assert not bumps_state_version(None, Elimination(True, 3, "adjudicator"))
