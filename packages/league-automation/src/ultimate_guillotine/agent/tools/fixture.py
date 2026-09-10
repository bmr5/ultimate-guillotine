"""The League Agent's deterministic 18-team fixture league.

It ships with the package rather than living beside the tests because two
callers outside the test suite need it. ``ug agent ask --fixture`` runs the
whole pipeline against this league so a prompt or scoring change can be tried
on a machine with no database and no league data at all, and the golden
request set in :mod:`tests.agent.test_golden` asks its live model questions
here rather than about real managers -- every name in it is ``Member07`` and
``Starter 07-3``, so a live transcript carries nothing about the league.

Nothing here reads a file, a connection or an environment variable: the whole
league is closed-form, so it is the same league on every machine and in every
season.

Team 1 is the strongest and team 18 sits on the cut line, strictly monotone, so
the pressure order is known by construction: pressure rank N is member N
counting up from the bottom. Team 17 is eliminated, which is what the
"never propose a trade with an eliminated team" tests need. Projections and
FAAB come from closed formulas rather than a data file: a reviewer can compute
any expected number by hand from the functions below.

**The rosters are not eighteen copies of one team.** A league where every roster
runs the identical lineup has no trade in it -- nobody is long anything anybody
else is short -- and a candidate generator tested against it would pass while
being unable to find a fit. So two things vary, both closed-form. The FLEX slot
and one bench spot rotate through :data:`ROTATION` by ``team % 4``, changing the
positional *shape* of each roster; and :func:`_positional_bonus` tilts each
team's points toward RB and away from WR (or the reverse) by ``team % 3``, so
some rosters are RB-rich and WR-poor while others are the mirror image and the
two have something to trade. The tilt is at most two points against a 7.2-point
gap between adjacent teams, so the pressure order above survives it untouched.

Points are ``Decimal``, matching what the data layer hands back for a ``numeric``
column, and each holding's ``projected_points`` is a mapping keyed by week over
``horizon_weeks``: a week further out is worth half a point less, which is
enough for a horizon to change an answer without inventing a projection model.

Below the coverage gate a team's own total is withheld -- the data layer will
not stand behind a projection it could not compute -- and by default this
fixture withholds each holding's points with it, which is the extreme case the
counting fallback has to survive. ``keep_player_points=True`` builds the case
the *real* snapshot produces: ``team_week_projections`` goes provisional while
the ``player_projections`` rows behind it sit there as numeric as ever. A
consumer that decides what to show by looking for holdings without numbers
passes the first case and leaks the second, so both are fixtures here.
"""

from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType

from ultimate_guillotine.agent.tools.snapshot import (
    COVERAGE_GATE,
    LAST_REGULAR_WEEK,
    LeagueHolding,
    LeagueSnapshot,
    LeagueTeamState,
)

FIXTURE_SYNCED_AT = datetime(2026, 10, 8, 15, 0, tzinfo=UTC)
FIXTURE_SEASON = 2026
FIXTURE_SEASON_ID = 1
ASKER_MEMBER_ID = 5
NEAR_CUT_MEMBER_ID = 18
ELIMINATED_MEMBER_ID = 17

#: Eight starter slots, then six bench spots, for all 18 teams.
LINEUP = ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX")
FLEX_POSITIONS = ("RB", "WR", "TE")
BENCH = ("RB", "WR", "WR", "TE", "QB", "RB")
#: The position that fills each lineup slot before the FLEX rotation is applied.
SLOT_POSITION = ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "WR")
#: The rotating positions, indexed by ``team % 4``: four teams in a row never run
#: the same shape, and the cycle is long enough to cross the ``% 3`` tilt.
ROTATION = ("RB", "WR", "TE", "WR")
#: The one starter slot and the one bench spot that rotate.
FLEX_SLOT_INDEX = 7
ROTATING_BENCH_INDEX = 1

_CENTS = Decimal("0.01")
#: A projection one week further out is worth half a point less. Not a model --
#: just enough slope that a two-week horizon and a one-week horizon differ.
_WEEK_DECAY = Decimal("0.5")


def _slot_position(team: int, slot_index: int) -> str:
    """The position filling a starter slot; the FLEX rotates by ``team % 4``."""
    if slot_index == FLEX_SLOT_INDEX:
        return ROTATION[team % 4]
    return SLOT_POSITION[slot_index]


def _bench_position(team: int, bench_index: int) -> str:
    """The position of a bench player; one spot rotates, offset from the FLEX."""
    if bench_index == ROTATING_BENCH_INDEX:
        return ROTATION[(team + 2) % 4]
    return BENCH[bench_index]


def _positional_bonus(team: int, position: str) -> Decimal:
    """Tilt a team toward RB and away from WR, or the reverse, by ``team % 3``.

    Zero-sum in spirit and tiny in size: at most one point per player, and at
    most two points on a team total, against the 7.2 points that separate
    adjacent teams. RB-rich teams are WR-poor and vice versa, which is exactly
    the asymmetry a trade has to be found in.
    """
    tilt = Decimal(team % 3 - 1)
    if position == "RB":
        return tilt
    if position == "WR":
        return -tilt
    return Decimal(0)


def _starter_points(team: int, slot_index: int) -> Decimal:
    """Strictly decreasing in team number and in slot index, then tilted."""
    base = Decimal(22) - Decimal("0.6") * team - Decimal("1.3") * slot_index
    return (base + _positional_bonus(team, _slot_position(team, slot_index))).quantize(_CENTS)


def _bench_points(team: int, bench_index: int) -> Decimal:
    base = Decimal(12) - Decimal("0.4") * team - Decimal("0.9") * bench_index
    return (base + _positional_bonus(team, _bench_position(team, bench_index))).quantize(_CENTS)


def _horizon(week: int, horizon_weeks: int) -> tuple[int, ...]:
    """The same cap ``SnapshotRepository.load`` applies, so the two agree."""
    last = max(week, min(week + horizon_weeks - 1, LAST_REGULAR_WEEK))
    return tuple(range(week, last + 1))


def _by_week(points: Decimal, weeks: tuple[int, ...]) -> MappingProxyType[int, Decimal]:
    return MappingProxyType(
        {w: (points - _WEEK_DECAY * (w - weeks[0])).quantize(_CENTS) for w in weeks}
    )


def _team(
    team: int,
    coverage_pct: Decimal,
    weeks: tuple[int, ...],
    keep_player_points: bool,
) -> LeagueTeamState:
    provisional = coverage_pct < COVERAGE_GATE
    #: A withheld team total does not withhold the players under it unless this
    #: fixture is asked to -- see the module docstring.
    dark = provisional and not keep_player_points
    holdings: list[LeagueHolding] = []
    total = Decimal(0)
    for slot_index, lineup_position in enumerate(LINEUP):
        points = _starter_points(team, slot_index)
        total += points
        holdings.append(
            LeagueHolding(
                sleeper_player_id=f"p{team:02d}s{slot_index}",
                player_name=f"Starter {team:02d}-{slot_index}",
                position=_slot_position(team, slot_index),
                slot="starter",
                lineup_position=lineup_position,
                slot_index=slot_index,
                week=weeks[0],
                projected_points={} if dark else _by_week(points, weeks),
            )
        )
    for bench_index in range(len(BENCH)):
        holdings.append(
            LeagueHolding(
                sleeper_player_id=f"p{team:02d}b{bench_index}",
                player_name=f"Bench {team:02d}-{bench_index}",
                position=_bench_position(team, bench_index),
                slot="bench",
                lineup_position=None,
                slot_index=None,
                week=weeks[0],
                projected_points=(
                    {} if dark else _by_week(_bench_points(team, bench_index), weeks)
                ),
            )
        )
    label = f"Member{team:02d}"
    return LeagueTeamState(
        team_id=100 + team,
        member_id=team,
        display_name=label,
        member_label=label,
        team_name=f"Team {team:02d}",
        sleeper_roster_id=team,
        faab_remaining=1000 - 40 * team,
        is_eliminated=team == ELIMINATED_MEMBER_ID,
        elimination_source="adjudicator" if team == ELIMINATED_MEMBER_ID else None,
        eliminated_week=weeks[0] - 1 if team == ELIMINATED_MEMBER_ID else None,
        week=weeks[0],
        projected_points={} if provisional else _by_week(total, weeks),
        coverage_pct=coverage_pct,
        is_provisional=provisional,
        holdings=tuple(holdings),
    )


def fixture_snapshot(
    week: int = 6,
    *,
    coverage_pct: Decimal = Decimal("100.00"),
    synced_at: datetime = FIXTURE_SYNCED_AT,
    oldest_synced_at: datetime | None = None,
    horizon_weeks: int = 1,
    keep_player_points: bool = False,
) -> LeagueSnapshot:
    """The league as one snapshot.

    ``synced_at`` is the newest component stamp and ``oldest_synced_at`` the one
    staleness is judged on; passing only ``synced_at`` makes every component the
    same age, which is the ordinary case.

    ``keep_player_points`` only means anything below the gate, where it leaves
    every holding's projection in place while the team totals stay withheld --
    the shape the real snapshot has, and the one a consumer can be fooled by.
    """
    weeks = _horizon(week, horizon_weeks)
    return LeagueSnapshot(
        season=FIXTURE_SEASON,
        season_id=FIXTURE_SEASON_ID,
        week=week,
        weeks=weeks,
        synced_at=synced_at,
        oldest_synced_at=synced_at if oldest_synced_at is None else oldest_synced_at,
        teams=tuple(_team(team, coverage_pct, weeks, keep_player_points) for team in range(1, 19)),
    )
