"""Every expected number here is derived from the fixture's closed formulas.

The fixture builds a starter at slot ``i`` on team ``t`` from
``22 - 0.6t - 1.3i`` plus a positional tilt of ``t % 3 - 1``, so a reviewer can
recompute any assertion below by hand. Where a value takes a merge of four
sources to derive -- the replacement level at RB, WR and TE -- the test asserts
the *definition* of an Nth-best instead of a hand-copied constant: at least N
projections at or above the level, fewer than N strictly above it. That holds
for any fixture, so the test keeps its meaning if the league's shape changes.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

from tests.advisor.fixture import (
    ASKER_MEMBER_ID,
    ELIMINATED_MEMBER_ID,
    NEAR_CUT_MEMBER_ID,
    fixture_snapshot,
)
from ultimate_guillotine.advisor.scoring import (
    FLEX_POSITIONS,
    NO_POINTS,
    POSITIONS,
    REPLACEMENT_RANK,
    ROSTER_POSITIONS,
    STARTER_SLOTS,
    UNRANKED,
    league_medians,
    need_ranks,
    pressure_order,
    replacement_levels,
    score_league,
    team_need,
    team_surplus,
)

LIVE_TEAMS = 17
#: 18 teams start one QB each and no fixture roster flexes a second one, so the
#: 18th-best QB is the worst team's starter: ``22 - 0.6 * 18``.
WORST_STARTING_QB = Decimal("11.20")
#: The 9th of 17 live teams' best starters, per position -- see the module
#: docstring. This is the *first* slot's median; the deeper slots are asserted
#: separately, because what makes them interesting is the empty ones.
EXPECTED_MEDIANS = {
    "QB": Decimal("16.60"),
    "RB": Decimal("15.10"),
    "WR": Decimal("12.30"),
    "TE": Decimal("8.80"),
}


def _projections_at(snapshot, position: str) -> list[Decimal]:
    return [
        holding.projected_now
        for team in snapshot.teams
        for holding in team.holdings
        if holding.position == position and holding.projected_now is not None
    ]


def test_pressure_order_puts_the_cut_line_first_and_drops_eliminated_teams() -> None:
    order = pressure_order(fixture_snapshot())
    assert order[0] == NEAR_CUT_MEMBER_ID
    assert ELIMINATED_MEMBER_ID not in order
    assert len(order) == LIVE_TEAMS


def test_pressure_order_is_stable_when_nothing_is_projected() -> None:
    order = pressure_order(fixture_snapshot(coverage_pct=Decimal("90.00")))
    assert order == tuple(m for m in range(1, 19) if m != ELIMINATED_MEMBER_ID)


def test_replacement_level_at_qb_is_the_worst_starting_quarterback() -> None:
    levels = replacement_levels(fixture_snapshot())
    assert set(levels) == set(POSITIONS)
    assert levels["QB"] == WORST_STARTING_QB


@pytest.mark.parametrize("position", POSITIONS)
def test_replacement_level_is_the_nth_best_projection_at_a_position(position: str) -> None:
    snapshot = fixture_snapshot()
    level = replacement_levels(snapshot)[position]
    points = _projections_at(snapshot, position)
    rank = REPLACEMENT_RANK[position]
    assert len(points) >= rank
    assert sum(1 for p in points if p >= level) >= rank
    assert sum(1 for p in points if p > level) < rank


def test_replacement_levels_are_zero_when_nothing_is_projected() -> None:
    levels = replacement_levels(fixture_snapshot(coverage_pct=Decimal("90.00")))
    assert levels == dict.fromkeys(POSITIONS, Decimal(0))


@pytest.mark.parametrize(("position", "expected"), sorted(EXPECTED_MEDIANS.items()))
def test_league_median_is_the_middle_teams_best_starter(position: str, expected: Decimal) -> None:
    assert league_medians(fixture_snapshot())[position][0] == expected


def test_starter_slots_count_the_flex_at_every_position_that_can_fill_it() -> None:
    base = {p: ROSTER_POSITIONS.count(p) for p in set(ROSTER_POSITIONS) if p != "FLEX"}
    assert STARTER_SLOTS == {
        p: count + (1 if p in FLEX_POSITIONS else 0) for p, count in base.items()
    }
    assert STARTER_SLOTS["RB"] == 3  # two starting slots plus the flex.
    assert STARTER_SLOTS["QB"] == 1


def test_a_median_is_as_deep_as_the_position_starts() -> None:
    medians = league_medians(fixture_snapshot())
    assert {p: len(v) for p, v in medians.items()} == {p: STARTER_SLOTS[p] for p in POSITIONS}
    # Every fixture team starts three wide receivers, so all three slots are real.
    assert all(value > NO_POINTS for value in medians["WR"])
    # Only a handful flex a running back or a second tight end, so the median
    # team has neither -- and a slot the median team leaves empty costs nobody.
    assert medians["RB"][2] == NO_POINTS
    assert medians["TE"][1] == NO_POINTS


@pytest.mark.parametrize(
    ("member_id", "expected"),
    [
        (1, Decimal("0.00")),  # 21.40 at QB, well above the 16.60 median.
        (9, Decimal("0.00")),  # exactly the median team: a gap of zero, not negative.
        (10, Decimal("0.60")),
        (NEAR_CUT_MEMBER_ID, Decimal("5.40")),  # 16.60 - 11.20.
    ],
)
def test_need_is_the_gap_to_the_league_median_and_never_negative(
    member_id: int, expected: Decimal
) -> None:
    snapshot = fixture_snapshot()
    medians = league_medians(snapshot)
    assert team_need(snapshot.team_for_member(member_id), "QB", medians) == expected


def test_an_unfilled_position_needs_the_whole_median() -> None:
    snapshot = fixture_snapshot()
    medians = league_medians(snapshot)
    team = snapshot.team_for_member(ASKER_MEMBER_ID)
    without_a_quarterback = replace(
        team, holdings=tuple(h for h in team.holdings if h.position != "QB")
    )
    assert team_need(without_a_quarterback, "QB", medians) == sum(medians["QB"])


def test_a_short_position_needs_the_median_for_each_missing_slot() -> None:
    """One running back where the league starts two: the second slot is a hole."""
    snapshot = fixture_snapshot()
    medians = league_medians(snapshot)
    team = snapshot.team_for_member(1)
    # Team 1's two starting backs project 20.10 and 18.80, both above the
    # league's 15.10 and 13.80, so a full lineup needs nothing at all.
    assert team_need(team, "RB", medians) == NO_POINTS
    one_back = replace(
        team,
        holdings=tuple(
            h
            for h in team.holdings
            if not (h.slot == "starter" and h.position == "RB" and h.slot_index == 2)
        ),
    )
    # The first slot is still covered; the empty second one costs its median.
    assert team_need(one_back, "RB", medians) == medians["RB"][1]


def test_a_filled_but_unprojected_starter_is_not_a_need() -> None:
    """A gap in the projection feed is not a gap in the roster."""
    snapshot = fixture_snapshot()
    medians = league_medians(snapshot)
    team = snapshot.team_for_member(NEAR_CUT_MEMBER_ID)
    assert team_need(team, "QB", medians) == Decimal("5.40")
    unprojected = replace(
        team,
        holdings=tuple(
            replace(h, projected_points={}) if h.position == "QB" and h.slot == "starter" else h
            for h in team.holdings
        ),
    )
    assert team_need(unprojected, "QB", medians) == NO_POINTS
    # Take the same player off the roster instead and the hole is real again.
    empty = replace(
        team,
        holdings=tuple(
            h for h in team.holdings if not (h.position == "QB" and h.slot == "starter")
        ),
    )
    assert team_need(empty, "QB", medians) == medians["QB"][0]


def test_surplus_is_bench_players_above_replacement_best_first() -> None:
    snapshot = fixture_snapshot()
    replacement = replacement_levels(snapshot)
    # Team 2 carries three bench running backs, two of them above the 10.50 line.
    surplus = team_surplus(snapshot.team_for_member(2), "RB", replacement)
    assert [h.sleeper_player_id for h in surplus] == ["p02b0", "p02b1"]
    assert all(h.slot == "bench" and h.position == "RB" for h in surplus)
    points = [h.projected_now for h in surplus]
    assert points == sorted(points, reverse=True)
    assert all(p > replacement["RB"] for p in points)


def test_surplus_is_empty_when_the_bench_is_below_replacement() -> None:
    snapshot = fixture_snapshot()
    replacement = replacement_levels(snapshot)
    # Member 18's only spare quarterback projects 1.20 against an 11.20 line.
    assert team_surplus(snapshot.team_for_member(NEAR_CUT_MEMBER_ID), "QB", replacement) == ()


def test_surplus_never_offers_a_starter() -> None:
    snapshot = fixture_snapshot()
    replacement = replacement_levels(snapshot)
    for team in snapshot.teams:
        for position in POSITIONS:
            assert all(
                h.slot == "bench" for h in team_surplus(team, position, replacement)
            )


def test_score_league_scores_every_member_the_same_way() -> None:
    scores = score_league(fixture_snapshot())
    assert len(scores) == 18
    assert scores[NEAR_CUT_MEMBER_ID].pressure_rank == 1
    assert scores[ELIMINATED_MEMBER_ID].is_eliminated
    assert scores[ELIMINATED_MEMBER_ID].pressure_rank == UNRANKED
    assert scores[ASKER_MEMBER_ID].faab_remaining == 1000 - 40 * ASKER_MEMBER_ID
    assert scores[ASKER_MEMBER_ID].member_label == "Member05"
    assert scores[ASKER_MEMBER_ID].projections_known
    assert set(scores[ASKER_MEMBER_ID].needs) == set(POSITIONS)


def test_sort_key_orders_by_pressure_and_leaves_the_unranked_last() -> None:
    """``UNRANKED`` is ``None``, which sorts nowhere on its own -- ``sort_key`` does."""
    scores = score_league(fixture_snapshot())
    order = [s.member_id for s in sorted(scores.values(), key=lambda s: s.sort_key)]
    assert order[0] == NEAR_CUT_MEMBER_ID
    assert order[-1] == ELIMINATED_MEMBER_ID
    assert scores[ELIMINATED_MEMBER_ID].pressure_rank is UNRANKED
    assert scores[order[1]].pressure_rank == 2


def test_a_score_follows_the_roster_and_not_the_member_id() -> None:
    """The fairness rule: relabel a member and nothing about the score moves."""
    snapshot = fixture_snapshot()
    before = score_league(snapshot)[ASKER_MEMBER_ID]
    relabelled = replace(
        snapshot,
        teams=tuple(
            replace(t, member_id=99) if t.member_id == ASKER_MEMBER_ID else t
            for t in snapshot.teams
        ),
    )
    after = score_league(relabelled)[99]
    assert after.needs == before.needs
    assert {p: [h.sleeper_player_id for h in hs] for p, hs in after.surpluses.items()} == {
        p: [h.sleeper_player_id for h in hs] for p, hs in before.surpluses.items()
    }
    assert after.pressure_rank == before.pressure_rank


@pytest.mark.parametrize(
    ("member_id", "expected"),
    [
        (NEAR_CUT_MEMBER_ID, 1),  # the biggest WR gap in the league, 4.00.
        (16, 2),
        (14, 3),
        (1, 9),  # first of the nine teams at or above the median, tied at zero.
        (ELIMINATED_MEMBER_ID, UNRANKED),
    ],
)
def test_need_ranks_are_one_based_and_biggest_need_first(member_id: int, expected: int) -> None:
    assert need_ranks(score_league(fixture_snapshot()), "WR")[member_id] == expected


def test_below_the_gate_needs_and_surpluses_fall_back_to_counting() -> None:
    scores = score_league(fixture_snapshot(coverage_pct=Decimal("90.00")))
    assert not scores[ASKER_MEMBER_ID].projections_known
    # Nobody has a numeric shortfall when nothing is projected, but positional
    # scarcity is still real: one RB on the bench is still a spare RB.
    assert all(value == Decimal(0) for value in scores[ASKER_MEMBER_ID].needs.values())
    assert scores[NEAR_CUT_MEMBER_ID].pressure_rank is UNRANKED
    assert [h.sleeper_player_id for h in scores[ASKER_MEMBER_ID].surpluses["RB"]] == [
        "p05b0",
        "p05b5",
    ]
    # With every need tied at zero the ranking is arbitrary, so it has to be
    # stable: member order, and the eliminated team still unranked.
    ranks = need_ranks(scores, "RB")
    assert ranks[ELIMINATED_MEMBER_ID] == UNRANKED
    ranked = sorted((rank, member_id) for member_id, rank in ranks.items() if rank != UNRANKED)
    assert [member_id for _, member_id in ranked] == [
        m for m in range(1, 19) if m != ELIMINATED_MEMBER_ID
    ]


def test_below_the_gate_counting_keys_on_the_gate_and_not_on_missing_numbers() -> None:
    """The real snapshot's below-gate shape: team totals withheld, players not.

    ``team_week_projections`` is what goes provisional; the
    ``player_projections`` rows behind it stay numeric. A fallback that switched
    on "no holding has a projection" would never fire here, and the Advisor
    would quote per-player numbers the gate had just withheld.
    """
    snapshot = fixture_snapshot(coverage_pct=Decimal("90.00"), keep_player_points=True)
    scores = score_league(snapshot)
    asker = snapshot.team_for_member(ASKER_MEMBER_ID)
    # The premise: every holding still carries a number, and the team does not.
    assert all(h.projected_now is not None for h in asker.holdings)
    assert asker.projected_now is None
    assert replacement_levels(snapshot)["QB"] == WORST_STARTING_QB

    assert not scores[ASKER_MEMBER_ID].projections_known
    assert all(value == NO_POINTS for value in scores[ASKER_MEMBER_ID].needs.values())
    # Counting bodies, not filtering by projection: member 18's lone spare
    # quarterback projects 1.20 against an 11.20 replacement line and would be
    # no surplus at all if the numbers were being read.
    assert [h.sleeper_player_id for h in scores[NEAR_CUT_MEMBER_ID].surpluses["QB"]] == ["p18b4"]
    assert [h.sleeper_player_id for h in scores[ASKER_MEMBER_ID].surpluses["RB"]] == [
        "p05b0",
        "p05b5",
    ]


def test_below_the_gate_no_team_has_a_pressure_rank() -> None:
    """One unknown, one treatment: nobody is ranked, not even the worst roster."""
    for snapshot in (
        fixture_snapshot(coverage_pct=Decimal("90.00")),
        fixture_snapshot(coverage_pct=Decimal("90.00"), keep_player_points=True),
    ):
        scores = score_league(snapshot)
        assert all(score.pressure_rank is UNRANKED for score in scores.values())
        # With nothing to rank on, sorting falls back to member order rather
        # than to whichever team happened to be listed first.
        order = [s.member_id for s in sorted(scores.values(), key=lambda s: s.sort_key)]
        assert order == list(range(1, 19))


def test_every_number_the_scoring_produces_is_a_decimal() -> None:
    snapshot = fixture_snapshot()
    assert all(isinstance(v, Decimal) for v in replacement_levels(snapshot).values())
    assert all(
        isinstance(value, Decimal)
        for slots in league_medians(snapshot).values()
        for value in slots
    )
    scores = score_league(snapshot)
    assert all(
        isinstance(value, Decimal) for score in scores.values() for value in score.needs.values()
    )
