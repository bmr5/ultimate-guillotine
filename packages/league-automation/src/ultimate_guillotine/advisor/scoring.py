"""How good every team is at every position, computed the same way for everyone.

Nothing in this module knows who is asking, and nothing takes a member id as
special. The spec's fairness rule -- "every member is scored by the same
deterministic function, no per-member weighting, no commissioner adjustment" --
is enforced by there being nowhere to put an exception: :func:`score_league`
runs one loop over ``snapshot.teams``, and every threshold it applies is a
module constant rather than an argument a caller could tilt.

Three questions are answered here, all of them per position:

* **Need** -- how far below the league's median *starting lineup* a team is.
  Measured against the median rather than the best team, because "worse than the
  best roster in the league" describes seventeen teams and tells nobody
  anything, and measured slot by slot rather than on the single best starter,
  because a league that starts two running backs cares about the second one.
* **Surplus** -- which *bench* players project above what a free replacement is
  worth. A starter is never surplus: trading it away opens the hole it fills.
* **Pressure** -- how close a team is to the guillotine, which in this league is
  simply this week's projected total, lowest first.

Every number is a :class:`~decimal.Decimal`, matching what the data layer hands
back for a ``numeric`` column: this module compares and subtracts projections,
and a float round-trip would round the league's arithmetic without ever
rounding it back. A missing projection -- a null ``league_points``, or a week
withheld below the coverage gate -- is ``None`` here too, never a zero.

Below the coverage gate the *team* numbers are gone but the shape of a roster is
not, so needs go to zero, pressure goes unranked, and surpluses fall back to
counting bodies at a position: the Advisor can still say "you are carrying three
tight ends" without quoting a projection it was told not to show. The gate is
the only thing that switches that fallback on. It deliberately does not key on
whether the holdings happen to carry projections, because they usually still do:
``team_week_projections`` is what goes provisional, and ``player_projections``
rows sit in the snapshot either way. Reading a per-player number the team-level
gate just withheld is exactly the leak the gate exists to prevent.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from typing import Final

from ultimate_guillotine.advisor.state import (
    AdvisorHolding,
    AdvisorTeamState,
    LeagueSnapshot,
)

#: The scoring positions. Kickers and defenses are deliberately absent: nobody
#: trades one, so neither is ever a need worth filling or a surplus worth
#: offering, however many of them the lineup starts.
POSITIONS = ("QB", "RB", "WR", "TE")
#: What may fill the FLEX slot.
FLEX_POSITIONS = ("RB", "WR", "TE")
#: The lineup slot that any of :data:`FLEX_POSITIONS` may fill.
FLEX_SLOT = "FLEX"
#: The league's starting lineup, one entry per slot, as ``sleeper.sync`` writes
#: it to ``public.seasons.roster_positions`` and ``sleeper.roster_state`` reads
#: it back. Kept here as a constant rather than read per run because a need is
#: only comparable across teams if every team is measured against one lineup.
ROSTER_POSITIONS = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF")
#: How many teams the league runs. Used only to turn lineup depth into a
#: league-wide player count.
LEAGUE_TEAMS = 18
#: The pressure or need rank of a team that is not in the running, and the rank
#: of every team when the gate withholds the projections a rank is made of.
#: ``None`` rather than a sentinel number: 0 sorts *first* under every ordinary
#: comparison, which would put an eliminated roster at the head of "who is about
#: to be cut". :meth:`TeamScore.sort_key` is what pushes it last instead.
UNRANKED: Final[None] = None
#: Points arrive quantized to cents from the data layer; a median of an even
#: number of teams is the one place this module can produce more places than
#: that, so it quantizes back.
POINT_PRECISION = Decimal("0.01")
#: What a level or a need is when there is nothing to measure -- no projections
#: at a position at all, or none anywhere. Not "worth zero points": unknown.
NO_POINTS = Decimal(0)


def _starter_slots() -> dict[str, int]:
    """How many starters of each position the league fields, FLEX included.

    The FLEX is one slot but three positions may fill it, and which one a team
    fills it with is a *choice*, not a fact about the position. So it adds a
    slot to each of :data:`FLEX_POSITIONS`: a team is measured as though it
    could flex any of them, and the extra slot costs nothing when the league at
    large leaves it empty, because a slot the median team does not fill has a
    median of :data:`NO_POINTS` and therefore no shortfall to make up.
    """
    slots: dict[str, int] = {}
    for position in ROSTER_POSITIONS:
        for counted in FLEX_POSITIONS if position == FLEX_SLOT else (position,):
            slots[counted] = slots.get(counted, 0) + 1
    return slots


#: Starting depth per position: QB 1, RB 3, WR 3, TE 2, K 1, DEF 1. Only the
#: :data:`POSITIONS` entries are ever read; the rest are here because the map is
#: derived from the whole lineup rather than hand-copied out of part of it.
STARTER_SLOTS = _starter_slots()

#: The Nth-best projection at a position is what a free replacement is worth, so
#: anything above it is surplus worth trading and anything below it is not. N is
#: :data:`LEAGUE_TEAMS` times how deep the league starts the position: one QB
#: (18) and one TE (18) each, two RBs (36), and WR three deep (54) because the
#: league's single FLEX slot is counted there, at the position that in practice
#: fills it, and nowhere else. It is counted *once*: adding it to RB and TE as
#: well -- the way :data:`STARTER_SLOTS` does, where an unfilled slot costs a
#: team nothing -- would invent two more starters per team than the league
#: fields and make replacement look cheaper than it is.
REPLACEMENT_RANK = {"QB": 18, "RB": 36, "WR": 54, "TE": 18}

__all__ = [
    "FLEX_POSITIONS",
    "FLEX_SLOT",
    "LEAGUE_TEAMS",
    "NO_POINTS",
    "POINT_PRECISION",
    "POSITIONS",
    "REPLACEMENT_RANK",
    "ROSTER_POSITIONS",
    "STARTER_SLOTS",
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

    ``pressure_rank`` is 1 for the team closest to the cut line, and
    :data:`UNRANKED` -- ``None`` -- for a team that is out of the running or when
    the coverage gate withheld the projections a rank is made of. Sort teams by
    :attr:`sort_key`, never by ``pressure_rank`` directly.
    """

    team_id: int
    member_id: int
    member_label: str
    needs: dict[str, Decimal]
    surpluses: dict[str, tuple[AdvisorHolding, ...]]
    faab_remaining: int
    pressure_rank: int | None
    is_eliminated: bool
    projections_known: bool

    @property
    def sort_key(self) -> tuple[int, int, int]:
        """Most guillotine pressure first, unranked teams last, ties by member id.

        ``None`` is not comparable to an ``int`` and would raise; a bare 0 *is*
        comparable and would sort an eliminated team ahead of the team actually
        about to be cut. The leading flag is what keeps unranked at the back.
        """
        return (self.pressure_rank is None, self.pressure_rank or 0, self.member_id)


def _at_position(holdings: Sequence[AdvisorHolding], position: str) -> list[AdvisorHolding]:
    return [h for h in holdings if h.position == position]


def _starters_at(team: AdvisorTeamState, position: str) -> tuple[list[Decimal], int]:
    """This team's starting projections at a position, best first, and how many bodies.

    The two numbers differ exactly when a starter is filled but unprojected, and
    that difference is the whole point: an *empty* slot is a hole worth the
    median, while a slot with a player nobody has projected is not a hole at
    all, just a number this module does not have.
    """
    starters = _at_position(team.starters(), position)
    points = sorted(
        (h.projected_now for h in starters if h.projected_now is not None), reverse=True
    )
    return points, len(starters)


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


def league_medians(snapshot: LeagueSnapshot) -> dict[str, tuple[Decimal, ...]]:
    """The median starting lineup at each position: one median per slot, best first.

    A position is as deep as :data:`STARTER_SLOTS` says, so the second running
    back is measured against the league's second running backs rather than
    against nobody. A team with no starter in a slot contributes
    :data:`NO_POINTS` to that slot's median -- an empty slot really does score
    nothing -- which is what makes the FLEX slot self-correcting: if most of the
    league does not flex a tight end, the second tight end's median is zero and
    nobody is charged for lacking one. A team whose starter in that slot is
    filled but unprojected contributes nothing at all, because that is unknown
    rather than zero.

    Eliminated teams are excluded so a dead roster cannot drag the league's idea
    of normal down and make everybody else look well stocked.
    """
    live = [team for team in snapshot.teams if not team.is_eliminated]
    medians: dict[str, tuple[Decimal, ...]] = {}
    for position in POSITIONS:
        lineups = [_starters_at(team, position) for team in live]
        per_slot: list[Decimal] = []
        for slot in range(STARTER_SLOTS.get(position, 0)):
            pool = [
                points[slot] if slot < len(points) else NO_POINTS
                for points, filled in lineups
                if slot < len(points) or slot >= filled
            ]
            per_slot.append(median(pool).quantize(POINT_PRECISION) if pool else NO_POINTS)
        medians[position] = tuple(per_slot)
    return medians


def team_need(
    team: AdvisorTeamState, position: str, medians: Mapping[str, Sequence[Decimal]]
) -> Decimal:
    """How far below the league's median starters this team is, never negative.

    Summed over the position's slots, each one clamped at zero: a team at or
    above the median in a slot has a need of zero there, not a negative one,
    because "less needy than normal" is not a thing to rank teams by and would
    otherwise let a stacked first slot pay for an empty second one.

    An *empty* slot costs the whole median for that slot -- nobody can project a
    slot the manager left blank, and a team with one starting running back needs
    a second one more than a team with a mediocre second one. A slot that is
    filled by a player nobody has projected costs :data:`NO_POINTS`: the roster
    hole is not there, only the number is, and charging a median for a missing
    projection would invent a need out of a gap in the feed.
    """
    pars = medians.get(position, ())
    points, filled = _starters_at(team, position)
    need = NO_POINTS
    for slot, par in enumerate(pars):
        if par == NO_POINTS:
            continue
        if slot < len(points):
            need += max(NO_POINTS, par - points[slot])
        elif slot >= filled:
            need += par
    return need


def team_surplus(
    team: AdvisorTeamState,
    position: str,
    replacement: Mapping[str, Decimal],
    *,
    projections_known: bool = True,
) -> tuple[AdvisorHolding, ...]:
    """Bench players at this position worth more than a free replacement, best first.

    Starters are never offered: a team that trades the player filling a slot has
    simply moved the hole. IR and taxi holdings are already out, because
    :meth:`AdvisorTeamState.bench` leaves them out.

    ``projections_known`` is the snapshot's coverage gate, handed down by
    :func:`score_league`. When it is false every bench player at the position
    counts, ordered by player id so the answer is stable: the roster still says
    the team is carrying spares even when nobody may be told how good they are.
    That fallback keys on the gate and on nothing else -- in particular not on
    whether these holdings carry projections, which below the gate they usually
    still do. The gate withholds the *team* projection; reading the per-player
    ones anyway would walk straight around it.
    """
    bench = _at_position(team.bench(), position)
    line = replacement.get(position, NO_POINTS)
    if not projections_known or line == NO_POINTS:
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
    pressure. The member id breaks ties so two identical projections never
    reorder run to run.

    Below the coverage gate no team has a projection at all and this degrades to
    member order, which is stable but means nothing. It is :func:`score_league`
    that refuses to hand out a rank in that case; this function is the ordering,
    not the judgement of whether the ordering is worth anything.
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
    """Score every team once, the same way. Keyed by member id, which candidates use.

    The coverage gate is read here, once, and handed to everything that needs to
    know: needs go to :data:`NO_POINTS`, every pressure rank goes
    :data:`UNRANKED` -- one unknown gets one treatment, so no caller can read a
    rank off a snapshot whose projections were withheld -- and surpluses fall
    back to counting bodies.
    """
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
                position: team_surplus(team, position, replacement, projections_known=known)
                for position in POSITIONS
            },
            faab_remaining=team.faab_remaining,
            pressure_rank=ranks.get(team.member_id, UNRANKED) if known else UNRANKED,
            is_eliminated=team.is_eliminated,
            projections_known=known,
        )
        for team in snapshot.teams
    }


def need_ranks(scores: Mapping[int, TeamScore], position: str) -> dict[int, int | None]:
    """1-based ranks at one position, biggest need first, ties broken by member id.

    Eliminated teams are :data:`UNRANKED` rather than missing: a caller that
    looks one up gets "not in the running" instead of a ``KeyError``, and
    ``None`` can never be mistaken for the top of the list.
    """
    ordered = sorted(
        (s for s in scores.values() if not s.is_eliminated),
        key=lambda s: (-s.needs.get(position, NO_POINTS), s.member_id),
    )
    ranks = {score.member_id: index + 1 for index, score in enumerate(ordered)}
    return {member_id: ranks.get(member_id, UNRANKED) for member_id in scores}
