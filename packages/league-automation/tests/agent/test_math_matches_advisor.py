"""The lifted arithmetic held against the Advisor's own, on the fixture league.

``agent/tools/math.py`` is a copy of what ``advisor/candidates.py`` and
``advisor/scoring.py`` compute, and a copy is only worth having if it is
faithful. These tests put the two side by side across the whole fixture league
and assert they agree -- function for function, value for value.

They also pin the one place the copy diverges on purpose. The Advisor's
``_lineup_delta`` takes a ``known`` coverage gate and returns ``None`` below it;
:func:`~ultimate_guillotine.agent.tools.math.lineup_delta` has no such
parameter, because the gate belongs at the tool boundary rather than inside the
arithmetic. So the copy matches the Advisor's ``known=True`` result always --
below the gate included -- and the ``known=False`` path is the Advisor's alone.

The Advisor modules go away in a later task, and this file goes with them, one
``git rm``. Until then the module-level ``importorskip`` calls make the whole
file skip cleanly rather than fail once they are gone.
"""

from decimal import Decimal

import pytest

from ultimate_guillotine.advisor.fixture import fixture_snapshot
from ultimate_guillotine.agent.tools.math import (
    lineup_delta,
    lineup_points,
    replacement_levels,
    startable,
)

candidates = pytest.importorskip("ultimate_guillotine.advisor.candidates")
scoring = pytest.importorskip("ultimate_guillotine.advisor.scoring")


def _best_rb(snapshot):
    return max(
        (h for t in snapshot.teams for h in t.holdings if h.position == "RB"),
        key=lambda h: h.projected_now,
    )


def _spare_wr(team):
    return next(h for h in team.bench() if h.position == "WR")


def test_startable_matches_the_advisor_for_every_team() -> None:
    snapshot = fixture_snapshot()
    for team in snapshot.teams:
        assert startable(team) == candidates._startable(team)


def test_lineup_points_matches_the_advisor_for_every_team_this_week() -> None:
    snapshot = fixture_snapshot()
    for team in snapshot.teams:
        holdings = startable(team)
        mine = lineup_points(holdings, snapshot.week)
        assert mine == candidates._lineup_points(holdings, snapshot.week)
        assert mine > Decimal(0)


def test_replacement_levels_matches_the_advisor() -> None:
    snapshot = fixture_snapshot()
    mine = replacement_levels(snapshot)
    assert mine == scoring.replacement_levels(snapshot)
    assert set(mine) == {"QB", "RB", "WR", "TE"}


def test_lineup_delta_matches_the_advisor_on_a_best_rb_acquisition() -> None:
    snapshot = fixture_snapshot()
    roster = startable(snapshot.team_for_member(18))
    incoming = [_best_rb(snapshot)]
    weeks = (snapshot.week,)
    mine = lineup_delta(roster, incoming, [], weeks)
    assert mine is not None
    assert mine == candidates._lineup_delta(roster, incoming, [], weeks, known=True)


def test_lineup_delta_matches_the_advisor_on_a_bench_wr_send_away() -> None:
    snapshot = fixture_snapshot()
    team = snapshot.team_for_member(5)
    roster = startable(team)
    outgoing = [_spare_wr(team)]
    weeks = (snapshot.week,)
    mine = lineup_delta(roster, [], outgoing, weeks)
    assert mine is not None
    assert mine == candidates._lineup_delta(roster, [], outgoing, weeks, known=True)


def test_below_the_gate_the_copy_matches_the_advisors_known_result() -> None:
    """Below the gate the two agree on the arithmetic and part on the gate.

    ``known=False`` is the Advisor's own refusal, not a property of the numbers:
    the per-player rows are as numeric as ever, and the copy adds them up. That
    is the documented divergence, so it is asserted here rather than assumed.
    """
    snapshot = fixture_snapshot(coverage_pct=Decimal("50.00"), keep_player_points=True)
    assert not snapshot.coverage_ok()
    weeks = (snapshot.week,)
    team = snapshot.team_for_member(18)
    roster = startable(team)
    incoming = [_best_rb(snapshot)]

    mine = lineup_delta(roster, incoming, [], weeks)
    assert mine is not None
    assert mine == candidates._lineup_delta(roster, incoming, [], weeks, known=True)
    assert candidates._lineup_delta(roster, incoming, [], weeks, known=False) is None
