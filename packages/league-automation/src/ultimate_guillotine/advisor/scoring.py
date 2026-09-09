"""How good every team is at every position, computed the same way for everyone.

Nothing in this module knows who is asking, and nothing takes a member id as
special. The spec's fairness rule -- "every member is scored by the same
deterministic function, no per-member weighting, no commissioner adjustment" --
is enforced by there being nowhere to put an exception: :func:`score_league`
runs one loop over ``snapshot.teams``, and every threshold it applies is a
module constant rather than an argument a caller could tilt.

Three questions are answered here, all of them per position:

* **Need** -- how far below the league's median starter a team is. Measured
  against the median rather than the best team, because "worse than the best
  roster in the league" describes seventeen teams and tells nobody anything.
* **Surplus** -- which *bench* players project above what a free replacement is
  worth. A starter is never surplus: trading it away opens the hole it fills.
* **Pressure** -- how close a team is to the guillotine, which in this league is
  simply this week's projected total, lowest first.

Every number is a :class:`~decimal.Decimal`, matching what the data layer hands
back for a ``numeric`` column: this module compares and subtracts projections,
and a float round-trip would round the league's arithmetic without ever
rounding it back. A missing projection -- a null ``league_points``, or a week
withheld below the coverage gate -- is ``None`` here too, never a zero.

Below the coverage gate the numbers are gone but the shape of a roster is not:
needs go to zero and surpluses fall back to counting bodies at a position, so
the Advisor can still say "you are carrying three tight ends" without ever
quoting a projection it was told not to show.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from ultimate_guillotine.advisor.state import (
    AdvisorHolding,
    AdvisorTeamState,
    LeagueSnapshot,
)

#: The scoring positions. Kickers and defenses are deliberately absent: the
#: league starts neither, so neither is ever a need or a surplus.
POSITIONS = ("QB", "RB", "WR", "TE")
#: What may fill the FLEX slot, which is why RB, WR and TE run deeper than QB.
FLEX_POSITIONS = ("RB", "WR", "TE")
#: How deep the league starts each position across 18 teams: one QB and one TE
#: each, two RBs, and three WRs plus a WR-heavy flex. The Nth-best projection at
#: a position is what a free replacement is worth, so anything above it is
#: surplus worth trading and anything below it is not.
REPLACEMENT_RANK = {"QB": 18, "RB": 36, "WR": 54, "TE": 18}
#: The pressure rank of a team that is not in the running: never 1, never last,
#: just not ranked. An eliminated team sorted as "least pressure" would read as
#: the safest roster in the league, which is exactly backwards.
UNRANKED = 0
#: Points arrive quantized to cents from the data layer; a median of an even
#: number of teams is the one place this module can produce more places than
#: that, so it quantizes back.
POINT_PRECISION = Decimal("0.01")
#: What a level or a need is when there is nothing to measure -- no projections
#: at a position at all, or none anywhere. Not "worth zero points": unknown.
NO_POINTS = Decimal(0)

__all__ = [
    "FLEX_POSITIONS",
    "NO_POINTS",
    "POINT_PRECISION",
    "POSITIONS",
    "REPLACEMENT_RANK",
    "UNRANKED",
    "TeamScore",
    "league_medians",
    "need_ranks",
    "pressure_order",
    "replacement_levels",
    "score_league",
    "team_need",
    "team_surplus",
]


@dataclass(frozen=True)
class TeamScore:
    """One team's needs, surpluses and standing, as the candidate generator reads them.

    ``member_label`` is the league's one public label for a member -- what gets
    rendered. The join key ``display_name`` is deliberately not carried: nothing
    downstream should print it, and it cannot be printed from here if it is not
    here. Holdings are unhashable (their projections are a mapping), so
    ``surpluses`` holds them in order rather than in a set.
    """

    team_id: int
    member_id: int
    member_label: str
    needs: dict[str, Decimal]
    surpluses: dict[str, tuple[AdvisorHolding, ...]]
    faab_remaining: int
    pressure_rank: int
    is_eliminated: bool
    projections_known: bool


def _at_position(holdings: Sequence[AdvisorHolding], position: str) -> list[AdvisorHolding]:
    return [h for h in holdings if h.position == position]


def _best_starter(team: AdvisorTeamState, position: str) -> Decimal | None:
    """This week's best projected starter at a position, or ``None`` if unknown.

    A slot nobody projected and a slot nobody filled look the same from here,
    and both are honestly "no number", which is what ``None`` says.
    """
    points = [
        h.projected_now
        for h in _at_position(team.starters(), position)
        if h.projected_now is not None
    ]
    return max(points) if points else None


def replacement_levels(snapshot: LeagueSnapshot) -> dict[str, Decimal]:
    """The projection of the Nth-best player at each position, league-wide.

    Every team counts, eliminated ones included: a player on a dead roster is
    still a player somebody in the league is holding, and pretending he is not
    rostered would make replacement look cheaper than it is.
    """
    levels: dict[str, Decimal] = {}
    for position in POSITIONS:
        points = sorted(
            (
                h.projected_now
                for team in snapshot.teams
                for h in _at_position(team.holdings, position)
                if h.projected_now is not None
            ),
            reverse=True,
        )
        rank = REPLACEMENT_RANK[position]
        levels[position] = points[rank - 1] if len(points) >= rank else NO_POINTS
    return levels


def league_medians(snapshot: LeagueSnapshot) -> dict[str, Decimal]:
    """The median team's best starter at each position -- what "normal" is.

    Eliminated teams are excluded so a dead roster cannot drag the league's idea
    of normal down and make everybody else look well stocked.
    """
    medians: dict[str, Decimal] = {}
    for position in POSITIONS:
        bests = [
            best
            for team in snapshot.teams
            if not team.is_eliminated
            for best in (_best_starter(team, position),)
            if best is not None
        ]
        medians[position] = median(bests).quantize(POINT_PRECISION) if bests else NO_POINTS
    return medians


def team_need(
    team: AdvisorTeamState, position: str, medians: Mapping[str, Decimal]
) -> Decimal:
    """How far below the league's median starter this team is, never negative.

    An unfilled or unprojected slot counts as the whole median: nobody can
    project a slot the manager left blank, and a team with no starting tight end
    needs one more than a team with a mediocre one. A team at or above the
    median has a need of zero -- not a negative one, because "less needy than
    normal" is not a thing to rank teams by.
    """
    par = medians.get(position, NO_POINTS)
    if par == NO_POINTS:
        return NO_POINTS
    best = _best_starter(team, position)
    if best is None:
        return par
    return max(NO_POINTS, par - best)


def team_surplus(
    team: AdvisorTeamState, position: str, replacement: Mapping[str, Decimal]
) -> tuple[AdvisorHolding, ...]:
    """Bench players at this position worth more than a free replacement, best first.

    Starters are never offered: a team that trades the player filling a slot has
    simply moved the hole. IR and taxi holdings are already out, because
    :meth:`AdvisorTeamState.bench` leaves them out.

    With no projections at all (below the coverage gate) every bench player at
    the position counts, ordered by player id so the answer is stable: the
    roster still says the team is carrying spares even when it cannot say how
    good they are.
    """
    bench = _at_position(team.bench(), position)
    line = replacement.get(position, NO_POINTS)
    if line == NO_POINTS or all(h.projected_now is None for h in bench):
        return tuple(sorted(bench, key=lambda h: h.sleeper_player_id))
    above = [h for h in bench if h.projected_now is not None and h.projected_now > line]
    return tuple(
        sorted(above, key=lambda h: (-(h.projected_now or NO_POINTS), h.sleeper_player_id))
    )


def pressure_order(snapshot: LeagueSnapshot) -> tuple[int, ...]:
    """Member ids from closest to the cut line outward, eliminated teams dropped.

    The guillotine takes the lowest score, so the lowest projected total is the
    most pressure and needs no other model. A team with no projection sorts
    last, behind every team that has one -- unknown pressure is not low
    pressure, and the caller is told projections are unknown by
    ``TeamScore.projections_known`` rather than by a number invented here. The
    member id breaks ties so two identical projections never reorder run to run.
    """
    live = [t for t in snapshot.teams if not t.is_eliminated]
    return tuple(
        team.member_id
        for team in sorted(
            live,
            key=lambda t: (
                t.projected_now is None,
                t.projected_now if t.projected_now is not None else NO_POINTS,
                t.member_id,
            ),
        )
    )


def score_league(snapshot: LeagueSnapshot) -> dict[int, TeamScore]:
    """Score every team once, the same way. Keyed by member id, which candidates use."""
    medians = league_medians(snapshot)
    replacement = replacement_levels(snapshot)
    ranks = {member_id: index + 1 for index, member_id in enumerate(pressure_order(snapshot))}
    known = snapshot.coverage_ok()
    return {
        team.member_id: TeamScore(
            team_id=team.team_id,
            member_id=team.member_id,
            member_label=team.member_label,
            needs={
                position: (team_need(team, position, medians) if known else NO_POINTS)
                for position in POSITIONS
            },
            surpluses={
                position: team_surplus(team, position, replacement) for position in POSITIONS
            },
            faab_remaining=team.faab_remaining,
            pressure_rank=ranks.get(team.member_id, UNRANKED),
            is_eliminated=team.is_eliminated,
            projections_known=known,
        )
        for team in snapshot.teams
    }


def need_ranks(scores: Mapping[int, TeamScore], position: str) -> dict[int, int]:
    """1-based ranks at one position, biggest need first, ties broken by member id.

    Eliminated teams are :data:`UNRANKED` rather than missing: a caller that
    looks one up gets "not in the running" instead of a ``KeyError``, and 0 can
    never be mistaken for the top of the list.
    """
    ordered = sorted(
        (s for s in scores.values() if not s.is_eliminated),
        key=lambda s: (-s.needs.get(position, NO_POINTS), s.member_id),
    )
    ranks = {score.member_id: index + 1 for index, score in enumerate(ordered)}
    return {member_id: ranks.get(member_id, UNRANKED) for member_id in scores}
