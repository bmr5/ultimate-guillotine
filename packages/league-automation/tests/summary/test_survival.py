"""The Monte Carlo: seeded, replayable, and right about the cases a person can check.

The assertions are on the certain cases -- a team with nothing left and the lowest
score is on the block with certainty; a gulag pair's odds sum to one -- and on one
open case whose probability a reader can bound by hand.
"""

from decimal import Decimal

from tests.summary.helpers import done_team, phase, snapshot, starter, team
from ultimate_guillotine.summary.survival import (
    DEFAULT_SIMULATIONS,
    MODEL_VERSION,
    input_hash,
    simulate,
)

ONE = Decimal(1)
ZERO = Decimal(0)


def _entry_week() -> tuple:
    return (done_team(1, "100"), done_team(2, "90"), done_team(3, "80"), done_team(4, "10"))


def test_the_same_inputs_replay_to_the_same_odds() -> None:
    snap = snapshot(_entry_week())
    first = simulate(snap, simulations=500)
    second = simulate(snap, simulations=500)
    assert first == second
    assert first.seed == second.seed
    assert first.model_version == MODEL_VERSION
    assert first.simulations == 500


def test_an_explicit_seed_is_recorded_and_honoured() -> None:
    snap = snapshot(_entry_week())
    result = simulate(snap, simulations=200, seed=7)
    assert result.seed == 7
    assert simulate(snap, simulations=200, seed=7) == result


def test_the_default_simulation_count_is_ten_thousand() -> None:
    assert DEFAULT_SIMULATIONS == 10_000


def test_a_settled_week_puts_the_bottom_two_on_the_block_with_certainty() -> None:
    result = simulate(snapshot(_entry_week()), simulations=100)
    odds = result.teams
    assert odds[4].probability == ONE
    assert odds[3].probability == ONE
    assert odds[2].probability == ZERO
    assert odds[1].probability == ZERO
    assert all(o.adverse_event == "gulag_entry" for o in odds.values())
    assert odds[4].pending == 0


def test_a_team_with_a_player_left_has_an_open_number() -> None:
    """A at 50 and B at 52 are done; D has one starter left projected 60 with the
    running-back spread (sigma 30). D lands on the block when he scores under 52,
    which a normal table puts near 39 percent; A is on it whatever happens."""
    teams = (
        done_team(1, "50"),
        done_team(2, "52"),
        done_team(3, "100"),
        team(4, points="0", starters=(starter("remaining", projected="60"),)),
    )
    result = simulate(snapshot(teams), simulations=4000, seed=1)
    d = result.teams[4]
    assert Decimal("0.30") < d.probability < Decimal("0.48")
    assert result.teams[1].probability == ONE
    assert result.teams[2].probability == ONE - d.probability
    assert result.teams[3].probability == ZERO
    assert d.pending == 1
    assert d.projected_final == Decimal(60)


def test_projected_final_is_points_so_far_plus_the_remaining_means() -> None:
    lineup = (
        starter("done", points="10.5"),
        starter("remaining", projected="8.25"),
        starter("live", projected="12", points="7"),
        starter("out", projected="15"),
    )
    result = simulate(
        snapshot((team(1, points="17.5", starters=lineup), done_team(2, "5"), done_team(3, "6"))),
        simulations=10,
    )
    # 17.5 scored + 8.25 to come + max(0, 12 - 7) still to come from the live starter.
    assert result.teams[1].projected_final == Decimal("30.75")
    assert result.teams[1].pending == 2


def test_a_gulag_pair_fight_only_each_other_and_their_odds_sum_to_one() -> None:
    teams = (
        done_team(1, "100"),
        done_team(2, "95"),
        done_team(3, "60"),
        done_team(4, "50"),
        done_team(5, "70"),
        done_team(6, "80"),
    )
    snap = snapshot(teams, week=5, phase_=phase(5, "gulag", gulag=(5, 6), source="events"))
    result = simulate(snap, simulations=100)
    assert result.teams[5].adverse_event == "gulag_loss"
    assert result.teams[6].adverse_event == "gulag_loss"
    assert result.teams[5].probability == ONE
    assert result.teams[6].probability == ZERO
    # The pool is the other four; 3 and 4 are its bottom two even though 5 scored less.
    assert result.teams[3].adverse_event == "gulag_entry"
    assert result.teams[3].probability == ONE
    assert result.teams[4].probability == ONE
    assert result.teams[1].probability == ZERO


def test_week_twelve_takes_the_gulag_loser_and_the_lowest_of_the_rest() -> None:
    teams = (
        done_team(1, "100"),
        done_team(2, "95"),
        done_team(3, "60"),
        done_team(4, "50"),
        done_team(5, "70"),
        done_team(6, "80"),
    )
    snap = snapshot(teams, week=12, phase_=phase(12, "double", gulag=(5, 6), source="events"))
    result = simulate(snap, simulations=100)
    assert result.teams[5].probability == ONE
    assert result.teams[4].adverse_event == "cut"
    assert result.teams[4].probability == ONE
    assert result.teams[3].probability == ZERO


def test_the_cut_weeks_take_the_lowest_score_of_everyone() -> None:
    teams = (done_team(1, "100"), done_team(2, "95"), done_team(3, "60"))
    snap = snapshot(teams, week=14, phase_=phase(14, "cut"))
    result = simulate(snap, simulations=100)
    assert result.teams[3].adverse_event == "cut"
    assert result.teams[3].probability == ONE
    assert result.teams[2].probability == ZERO


def test_the_final_names_the_runner_up() -> None:
    snap = snapshot((done_team(1, "100"), done_team(2, "95")), week=17, phase_=phase(17, "final"))
    result = simulate(snap, simulations=100)
    assert result.teams[2].adverse_event == "title_loss"
    assert result.teams[2].probability == ONE
    assert result.teams[1].probability == ZERO


def test_an_eliminated_team_is_in_no_pool() -> None:
    teams = (
        done_team(1, "100"),
        done_team(2, "90"),
        done_team(3, "80"),
        done_team(4, "0", eliminated=True, eliminated_week=3),
    )
    result = simulate(
        snapshot(teams, week=4, phase_=phase(4, "gulag", gulag=(), source="unknown")),
        simulations=100,
    )
    assert 4 not in result.teams
    assert result.teams[3].probability == ONE
    assert result.teams[2].probability == ONE


def test_an_unknown_gulag_pairing_makes_everyone_the_pool() -> None:
    teams = (done_team(1, "100"), done_team(2, "90"), done_team(3, "80"), done_team(4, "70"))
    snap = snapshot(teams, week=5, phase_=phase(5, "gulag", gulag=(), source="unknown"))
    result = simulate(snap, simulations=100)
    assert {o.adverse_event for o in result.teams.values()} == {"gulag_entry"}
    assert result.teams[4].probability == ONE
    assert result.teams[3].probability == ONE


def test_a_pending_starter_with_no_projection_is_estimated_at_his_position_median() -> None:
    teams = (
        team(1, points="0", starters=(starter("remaining", projected=None, position="WR"),)),
        team(2, points="0", starters=(starter("remaining", projected="20", position="WR"),)),
        team(3, points="0", starters=(starter("remaining", projected="10", position="WR"),)),
        done_team(4, "100"),
    )
    result = simulate(snapshot(teams), simulations=100)
    assert result.teams[1].is_estimated
    assert result.teams[1].projected_final == Decimal(15)
    assert not result.teams[2].is_estimated


def test_a_pending_starter_with_no_projection_and_no_median_counts_for_nothing() -> None:
    teams = (
        team(1, points="0", starters=(starter("remaining", projected=None, position="K"),)),
        done_team(2, "100"),
        done_team(3, "90"),
    )
    result = simulate(snapshot(teams), simulations=50)
    assert result.teams[1].is_estimated
    assert result.teams[1].projected_final == ZERO


def test_the_season_being_over_yields_no_result() -> None:
    snap = snapshot((done_team(1, "1"),), week=18, phase_=phase(18, "over"))
    assert simulate(snap, simulations=10) is None


def test_too_few_teams_for_the_event_yields_zero_odds_not_a_crash() -> None:
    result = simulate(snapshot((done_team(1, "10"),)), simulations=10)
    assert result.teams[1].probability == ZERO


def test_the_input_hash_moves_with_a_score_and_holds_otherwise() -> None:
    base = snapshot(_entry_week())
    moved = snapshot(
        (done_team(1, "100"), done_team(2, "90"), done_team(3, "80"), done_team(4, "11"))
    )
    assert input_hash(base) == input_hash(snapshot(_entry_week()))
    assert input_hash(base) != input_hash(moved)
    assert len(input_hash(base)) == 64


def test_the_input_hash_moves_with_the_gulag_pairing() -> None:
    teams = _entry_week()
    a = snapshot(teams, week=3, phase_=phase(3, "gulag", gulag=(1, 2), source="events"))
    b = snapshot(teams, week=3, phase_=phase(3, "gulag", gulag=(1, 3), source="events"))
    assert input_hash(a) != input_hash(b)
