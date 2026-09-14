import random
from dataclasses import replace
from decimal import Decimal
from statistics import mean, variance

import pytest

from tests.summary.helpers import done_team, snapshot, starter, team
from ultimate_guillotine.summary.agent import build_packet
from ultimate_guillotine.summary.distributions import draw_points, parameters
from ultimate_guillotine.summary.evaluation import evaluate
from ultimate_guillotine.summary.replay import decode, encode, replay
from ultimate_guillotine.summary.schedule import parse_clocks
from ultimate_guillotine.summary.survival import input_hash, simulate, starter_draw


def test_gamma_preserves_mean_and_variance_without_clipping_bias():
    rng = random.Random(83)
    draws = [draw_points(rng, 10, 81, "WR", 0.15) for _ in range(100_000)]
    assert mean(draws) == pytest.approx(10, abs=0.1)
    assert variance(draws) == pytest.approx(81, rel=0.025)
    assert sum(x == 0 for x in draws) / len(draws) == pytest.approx(0.15, abs=0.005)
    assert max(draws) > 40


def test_signed_defense_deltas_can_lower_a_team_score():
    rng = random.Random(4)
    draws = [draw_points(rng, -2, 9, "DEF") for _ in range(20_000)]
    assert mean(draws) == pytest.approx(-2, abs=0.08)
    assert min(draws) < -5
    defense = replace(
        starter("live", position="DEF", projected="6", points="10"),
        remaining_fraction=Decimal(".5"),
    )
    assert starter_draw(defense, {}).mean == -2
    snap = snapshot(
        (team(1, points="10", starters=(defense,)), done_team(2, "9"), done_team(3, "0"))
    )
    result = simulate(snap, simulations=2000)
    assert result.teams[1].projected_final == 8
    assert 0 < result.teams[1].probability < 1


def test_remaining_mean_and_variance_shrink_with_clock_and_finish_at_actual():
    player = replace(starter("live", projected="20", points="4"), remaining_fraction=Decimal(".5"))
    half = starter_draw(player, {})
    quarter = starter_draw(replace(player, remaining_fraction=Decimal(".25")), {})
    assert half.mean == 10 and quarter.mean == 5
    assert quarter.sigma**2 == pytest.approx(half.sigma**2 / 2)
    final = starter_draw(replace(player, remaining_fraction=Decimal(0)), {})
    assert final.mean == final.sigma == 0
    with pytest.raises(ValueError):
        starter_draw(replace(player, remaining_fraction=None), {})
    snap = snapshot(
        (
            team(1, starters=(replace(player, remaining_fraction=None),)),
            done_team(2, "0"),
            done_team(3, "1"),
        )
    )
    assert build_packet(snap).no_odds_reason == "live game clocks unavailable"


def test_archived_inputs_replay_after_json_round_trip():
    snap = snapshot(
        (
            team(
                1,
                points="4",
                starters=(replace(starter("live"), remaining_fraction=Decimal(".333333")),),
            ),
            done_team(2, "5"),
            done_team(3, "15"),
        )
    )
    result = simulate(snap, simulations=500, seed=2**64 - 1)
    payload = encode(snap, result)
    assert decode(payload) == snap
    assert replay(payload) == result
    changed = replace(
        snap,
        teams=(
            replace(
                snap.teams[0],
                starters=(replace(snap.teams[0].starters[0], remaining_fraction=Decimal(".2")),),
            ),
            *snap.teams[1:],
        ),
    )
    assert input_hash(changed) != input_hash(snap)
    model = {**parameters(), "version": "different-fit"}
    assert input_hash(snap, model) != input_hash(snap)


def test_clock_scope_halftime_overtime_and_final():
    def feed(period, clock, state="in"):
        return {
            "season": {"year": 2026, "type": 2},
            "week": {"number": 1},
            "events": [
                {
                    "id": "a",
                    "season": {"year": 2026, "type": 2},
                    "week": {"number": 1},
                    "status": {
                        "period": period,
                        "clock": clock,
                        "type": {"state": state, "completed": state == "post"},
                    },
                    "competitions": [
                        {
                            "competitors": [
                                {"team": {"abbreviation": "WSH"}},
                                {"team": {"abbreviation": "JAC"}},
                            ]
                        }
                    ],
                }
            ],
        }

    assert parse_clocks(feed(2, 0), 2026, 1)["WAS"].remaining_fraction == Decimal(".5")
    assert parse_clocks(feed(5, 600), 2026, 1)["JAX"].remaining_fraction == Decimal(1) / 6
    assert parse_clocks(feed(4, 0, "post"), 2026, 1)["WAS"].remaining_fraction == 0
    with pytest.raises(ValueError):
        parse_clocks(feed(2, 0), 2026, 2)


def test_evaluation_deduplicates_live_ticks_and_keeps_final_weeks_only():
    snap = snapshot((done_team(1, "10"), done_team(2, "20"), done_team(3, "30")))
    result = simulate(snap, simulations=10)
    from ultimate_guillotine.summary.store import results_payload

    f = {
        "season_id": 1,
        "week": 1,
        "model_version": result.model_version,
        "snapshot_at": "2026-09-13",
        "inputs": encode(snap, result),
        "results": results_payload(snap, result),
    }
    assert evaluate([f], {}, {})["cohorts"] == []
    scores = {(1, 1): {1: 10, 2: 20, 3: 30}}
    report = evaluate([f, {**f, "snapshot_at": "2026-09-14"}], scores, {})
    assert report["cohorts"][0]["teams"] == 3
    assert report["cohorts"][0]["brier"] == 0
    assert evaluate([f], {(1, 1): {1: 10, 2: 20, 3: 20}}, {})["ambiguous_weeks"] == 1


def test_a_clock_outage_withholds_odds_even_if_sleeper_schedule_is_cached():
    from ultimate_guillotine.summary.schedule import fetch_week_games

    class Client:
        def get_schedule(self, season):
            return [{"game_id": "a", "week": 1, "home": "DAL", "away": "NYG", "status": "pre_game"}]

        def get_game_clocks(self, season, week):
            raise TimeoutError()

    assert fetch_week_games(Client(), 2026, 1) is None


def test_lineup_mismatch_withholds_instead_of_mixing_score_and_projection():
    snap = snapshot(
        (replace(done_team(1, "20"), lineup_matches=False), done_team(2, "10"), done_team(3, "5"))
    )
    assert build_packet(snap).result is None
    assert "matching lineup" in build_packet(snap).no_odds_reason


def test_evaluation_counts_final_lineup_changes_separately():
    from ultimate_guillotine.summary.store import results_payload

    snap = snapshot((done_team(1, "10"), done_team(2, "20"), done_team(3, "30")))
    result = simulate(snap, simulations=10)
    f = {
        "season_id": 1,
        "week": 1,
        "model_version": result.model_version,
        "snapshot_at": "2026-09-13",
        "inputs": encode(snap, result),
        "results": results_payload(snap, result),
    }
    scores = {(1, 1): {1: 10, 2: 20, 3: 30}}
    lineups = {(1, 1, 1): ["different"], (1, 1, 2): ["p-RB-done"], (1, 1, 3): ["p-RB-done"]}
    report = evaluate([f], scores, lineups)["cohorts"][0]
    assert report["lineups_changed"] == 1
    assert report["unchanged_brier"] == 0
