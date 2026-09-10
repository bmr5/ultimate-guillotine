"""Lineup arithmetic: what a set of players is worth as a starting lineup.

Lifted from the Trade Advisor's candidate generator, where it was the one part
worth keeping: a model with rosters in front of it will happily add gross
projections together, and gross projections make every trade zero-sum. What a
player is *worth to a roster* is the margin over whoever he displaces from the
best legal lineup, and that is what :func:`lineup_delta` computes, for each
side against its own roster.

The FLEX is left out of the depth on purpose: it is one slot three positions
may fill, and counting it at each of them would invent two starters per team.
A missing projection makes a total unknown rather than smaller -- ``None``,
never zero -- because a lineup a man short is not a cheaper lineup.
"""

from collections.abc import Mapping, Sequence
from decimal import Decimal

from ultimate_guillotine.advisor.state import (
    AdvisorHolding,
    AdvisorTeamState,
    LeagueSnapshot,
)

POSITIONS = ("QB", "RB", "WR", "TE")
ROSTER_POSITIONS = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF")
FLEX_SLOT = "FLEX"
LEAGUE_TEAMS = 18
#: The Nth-best projection at a position is what a free replacement is worth.
#: The single FLEX is counted once, at WR, the position that in practice fills it.
REPLACEMENT_RANK = {"QB": 18, "RB": 36, "WR": 54, "TE": 18}
NO_POINTS = Decimal(0)
POINT_PRECISION = Decimal("0.01")


def _starter_slots() -> dict[str, int]:
    slots: dict[str, int] = {}
    for position in ROSTER_POSITIONS:
        if position == FLEX_SLOT:
            continue
        slots[position] = slots.get(position, 0) + 1
    return slots


#: Starting depth per position with the FLEX left out: QB 1, RB 2, WR 2, TE 1.
STARTER_SLOTS = _starter_slots()

__all__ = [
    "LEAGUE_TEAMS",
    "NO_POINTS",
    "POINT_PRECISION",
    "POSITIONS",
    "REPLACEMENT_RANK",
    "STARTER_SLOTS",
    "lineup_delta",
    "lineup_points",
    "replacement_levels",
    "startable",
]


def replacement_levels(snapshot: LeagueSnapshot) -> dict[str, Decimal]:
    """The projection of the Nth-best rostered player at each position, league-wide."""
    levels: dict[str, Decimal] = {}
    for position in POSITIONS:
        points = sorted(
            (
                h.projected_now
                for team in snapshot.teams
                for h in team.holdings
                if h.position == position and h.projected_now is not None
            ),
            reverse=True,
        )
        rank = REPLACEMENT_RANK[position]
        levels[position] = points[rank - 1] if len(points) >= rank else NO_POINTS
    return levels


def startable(team: AdvisorTeamState) -> tuple[AdvisorHolding, ...]:
    """The players a team may actually field: starters and bench, never IR or taxi."""
    return team.starters() + team.bench()


def lineup_points(holdings: Sequence[AdvisorHolding], week: int) -> Decimal:
    """The best legal base lineup these players can field in one week."""
    total = NO_POINTS
    for position in POSITIONS:
        slots = STARTER_SLOTS.get(position, 0)
        projections = sorted(
            (
                projected
                for holding in holdings
                if holding.position == position
                and (projected := holding.projected_for(week)) is not None
            ),
            reverse=True,
        )
        total += sum(projections[:slots], NO_POINTS)
    return total


def _contenders(
    roster: Sequence[AdvisorHolding], moving: Sequence[AdvisorHolding]
) -> list[AdvisorHolding]:
    """Everybody whose projection the diff depends on: the movers and every
    incumbent at a position the trade touches."""
    affected = {
        h.position for h in moving if h.position is not None and STARTER_SLOTS.get(h.position, 0)
    }
    return list(moving) + [h for h in roster if h.position in affected]


def lineup_delta(
    roster: Sequence[AdvisorHolding],
    incoming: Sequence[AdvisorHolding],
    outgoing: Sequence[AdvisorHolding],
    weeks: Sequence[int],
) -> Decimal | None:
    """What these legs do to one side's best lineup, summed over ``weeks``.

    ``None`` when anybody who could contest the touched slots has no projection
    for a covered week: a lineup a man short is unknown, not smaller.
    """
    moving = list(incoming) + list(outgoing)
    if any(h.projected_for(week) is None for h in _contenders(roster, moving) for week in weeks):
        return None
    leaving = {h.sleeper_player_id for h in outgoing}
    before = list(roster)
    after = [h for h in before if h.sleeper_player_id not in leaving] + list(incoming)
    total = NO_POINTS
    for week in weeks:
        total += lineup_points(after, week) - lineup_points(before, week)
    return total.quantize(POINT_PRECISION)


def holdings_by_id(
    snapshot: LeagueSnapshot,
) -> Mapping[str, tuple[AdvisorTeamState, AdvisorHolding]]:
    """Every rostered player, keyed by Sleeper id, with the team holding him."""
    return {h.sleeper_player_id: (team, h) for team in snapshot.teams for h in team.holdings}
