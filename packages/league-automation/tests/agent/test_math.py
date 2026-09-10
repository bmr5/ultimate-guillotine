"""The lineup arithmetic every trade tool prices with, lifted from the Advisor.

Same numbers as the Advisor's candidate generator computed, tested here against
the fixture league so the move under ``agent/tools`` changes nothing.
"""

from decimal import Decimal

from ultimate_guillotine.advisor.fixture import fixture_snapshot
from ultimate_guillotine.agent.tools.math import (
    POSITIONS,
    STARTER_SLOTS,
    lineup_delta,
    lineup_points,
    replacement_levels,
    startable,
)


def _team(snapshot, member_id):
    return snapshot.team_for_member(member_id)


def test_the_base_lineup_has_no_flex_slot() -> None:
    assert POSITIONS == ("QB", "RB", "WR", "TE")
    assert {p: STARTER_SLOTS[p] for p in POSITIONS} == {"QB": 1, "RB": 2, "WR": 2, "TE": 1}


def test_replacement_levels_are_the_nth_best_rostered_projection() -> None:
    levels = replacement_levels(fixture_snapshot())
    assert set(levels) == set(POSITIONS)
    assert all(isinstance(v, Decimal) for v in levels.values())
    # Eighteen QBs are started league-wide, so the 18th-best QB is the line.
    qbs = sorted(
        (h.projected_now for t in fixture_snapshot().teams for h in t.holdings
         if h.position == "QB" and h.projected_now is not None),
        reverse=True,
    )
    assert levels["QB"] == qbs[17]


def test_lineup_points_sums_the_best_legal_starters_only() -> None:
    snapshot = fixture_snapshot()
    team = _team(snapshot, 5)
    total = lineup_points(startable(team), snapshot.week)
    by_hand = Decimal(0)
    for position in POSITIONS:
        points = sorted(
            (h.projected_now for h in startable(team) if h.position == position),
            reverse=True,
        )
        by_hand += sum(points[: STARTER_SLOTS[position]], Decimal(0))
    assert total == by_hand


def test_an_upgrade_is_worth_the_margin_over_the_displaced_starter() -> None:
    snapshot = fixture_snapshot()
    team = _team(snapshot, 18)
    best_rb = max(
        (h for t in snapshot.teams for h in t.holdings if h.position == "RB"),
        key=lambda h: h.projected_now,
    )
    delta = lineup_delta(startable(team), [best_rb], [], (snapshot.week,))
    starters = sorted(
        (h.projected_now for h in startable(team) if h.position == "RB"), reverse=True
    )
    assert delta == (best_rb.projected_now - starters[1]).quantize(Decimal("0.01"))


def test_a_bench_for_bench_move_is_worth_nothing() -> None:
    snapshot = fixture_snapshot()
    team = _team(snapshot, 5)
    spare = next(h for h in team.bench() if h.position == "WR")
    assert lineup_delta(startable(team), [], [spare], (snapshot.week,)) == Decimal("0.00")


def test_a_missing_projection_makes_the_delta_unknown() -> None:
    snapshot = fixture_snapshot(coverage_pct=Decimal("50.00"))
    team = _team(snapshot, 5)
    incoming = next(h for t in snapshot.teams for h in t.holdings if h.position == "RB")
    assert lineup_delta(startable(team), [incoming], [], (snapshot.week,)) is None
