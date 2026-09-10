"""League Agent lineup arithmetic checked against hand-calculated fixture values."""

from decimal import Decimal

from ultimate_guillotine.agent.tools import math as lineup_math
from ultimate_guillotine.agent.tools.fixture import fixture_snapshot
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


def test_a_holding_with_no_projection_makes_the_delta_unknown() -> None:
    """A blank projection, not the coverage percentage, is what does this.

    ``fixture_snapshot`` strips the per-holding numbers along with the team
    totals by default, and it is the missing per-holding numbers the delta
    refuses to guess at: a lineup a man short is unknown, not smaller. The
    coverage gate itself does nothing here -- see the sibling below.
    """
    snapshot = fixture_snapshot(coverage_pct=Decimal("50.00"))
    team = _team(snapshot, 5)
    incoming = next(h for t in snapshot.teams for h in t.holdings if h.position == "RB")
    assert lineup_delta(startable(team), [incoming], [], (snapshot.week,)) is None


def test_below_the_gate_with_points_intact_the_delta_is_a_number() -> None:
    """The coverage gate is the caller's business, not this module's.

    Below the gate the team totals go provisional while the per-player rows keep
    their numbers -- the shape the real snapshot has -- and ``lineup_delta`` adds
    up whatever rows it is handed. Per-player projections are public on the
    league board even then, so this is not a leak; it is the contract, pinned
    here so it stays a decision rather than an accident.
    """
    snapshot = fixture_snapshot(coverage_pct=Decimal("50.00"), keep_player_points=True)
    assert not snapshot.coverage_ok()
    team = _team(snapshot, 5)
    incoming = next(h for t in snapshot.teams for h in t.holdings if h.position == "RB")
    delta = lineup_delta(startable(team), [incoming], [], (snapshot.week,))
    assert isinstance(delta, Decimal)


def test_the_public_surface_lists_the_holdings_index() -> None:
    assert "holdings_by_id" in lineup_math.__all__
    assert all(hasattr(lineup_math, name) for name in lineup_math.__all__)
