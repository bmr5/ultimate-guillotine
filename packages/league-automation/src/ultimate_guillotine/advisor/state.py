"""One read of the league data layer, cached for the length of one advice run.

The Advisor reads rosters, projections, FAAB and elimination once per run and
reuses that snapshot for every candidate: a run that re-queried per candidate
would be both slow and internally inconsistent, proposing a trade against two
different versions of the same roster.

Every table here belongs to the league data layer spec. Nothing in this module
writes, and nothing here invents a number: a null ``league_points`` stays
``None`` all the way to the formatter, because a missing projection is not a
zero. Below the coverage gate the projection is withheld outright, which is
what the data layer requires of every consumer. Points and coverage stay
``Decimal`` end to end -- psycopg hands back ``Decimal`` for a ``numeric``
column, and casting to ``float`` here would round the league's arithmetic on the
way in and never round it back. FAAB is an ``int`` because the column is one.

The dataclasses are named ``Advisor*`` on purpose. ``sleeper.roster_state``
already owns a ``Holding`` and a ``TeamState``, and those are *write* shapes --
what one Sleeper payload classified into. These are *read* shapes: a holding
here carries the player's name and his projected points, which the sync's
holding never does. Two different things with one name in two modules is how a
later import lands on the wrong one silently, so they keep different names.

**Staleness is measured on the oldest component, not the newest.** A snapshot is
stitched from four independently synced sources -- the NFL state row, each team's
season state, the team-week projections, and the roster holdings. Gating on the
newest of those lets one fresh sync vouch for three stale ones: a roster sync
that stalled six hours ago reads as current the moment the projection job runs.
So ``synced_at`` stays the newest stamp, which is the honest thing to *display*
("last updated"), and ``oldest_synced_at`` -- the ``least`` of the same set --
is what :meth:`LeagueSnapshot.age` and :meth:`LeagueSnapshot.is_stale` answer
from. A component that is missing outright is not old, it is unknown, and the
snapshot refuses to load rather than standing in an epoch timestamp that would
either make everything permanently stale or, coalesced the other way, make a
missing sync invisible.

**Projections are read over a horizon of weeks, not just this one.** A trade is
paid for over the weeks that follow it, so ``load(horizon_weeks=n)`` reads
``player_projections`` and ``team_week_projections`` for weeks ``week`` through
``week + n - 1``, capped at :data:`LAST_REGULAR_WEEK`. Each holding's
``projected_points`` is a mapping keyed by week; ``projected_now`` is the
current week's entry, and a week with no projection is simply absent from the
mapping rather than present as a zero.

**An eliminated team's holdings come from its frozen roster when it has one.**
``public.roster_holdings`` is current-state only and a manager who is out goes
on dropping and adding, so reading it would offer trades over players the team
did not go out with. ``public.final_rosters.holdings`` is the roster it was
eliminated with, written once and never rewritten, and that is what an
eliminated team shows here. A team marked eliminated by hand and never synced
since has no frozen snapshot, and falls back to its live holdings -- the same
precedence ``sleeper.team_projections`` applies to the projection arithmetic.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

import psycopg

from ultimate_guillotine.sleeper.state import NflStateRepository
from ultimate_guillotine.sleeper.team_projections import COVERAGE_GATE

#: The data layer's staleness window: past this the Advisor reports the age of
#: what it has instead of advising from it.
STALE_AFTER = timedelta(minutes=30)

#: The last week of the NFL regular season. Neither the data layer nor Sleeper's
#: ``nfl_state`` row carries the number -- ``nfl_state.week`` is only ever "the
#: week we are in" -- so the horizon is capped against a named constant here
#: rather than a bare 18 inside the arithmetic. The regular season has been 18
#: weeks since 2021; if the league ever changes it, this is the one line.
LAST_REGULAR_WEEK = 18

_NO_POINTS: Mapping[int, Decimal] = MappingProxyType({})

__all__ = [
    "COVERAGE_GATE",
    "LAST_REGULAR_WEEK",
    "STALE_AFTER",
    "AdvisorHolding",
    "AdvisorTeamState",
    "LeagueSnapshot",
    "SnapshotRepository",
    "SnapshotUnavailable",
]


class SnapshotUnavailable(Exception):
    """Raised when the data layer cannot answer what week or league this is."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AdvisorHolding:
    """One rostered player, with the name and the numbers the Advisor renders.

    ``projected_points`` is keyed by NFL week over the snapshot's horizon. A week
    the feed has no number for is *absent* from the mapping, never present as a
    zero, so a consumer that asks for a week it was not given gets ``None`` and
    has to say so.
    """

    sleeper_player_id: str
    player_name: str
    position: str | None
    slot: str
    lineup_position: str | None
    slot_index: int | None
    #: The snapshot's current week, so ``projected_now`` needs no argument.
    week: int
    projected_points: Mapping[int, Decimal]

    @property
    def projected_now(self) -> Decimal | None:
        """This week's projection, or ``None`` when there is not one."""
        return self.projected_points.get(self.week)

    def projected_for(self, week: int) -> Decimal | None:
        return self.projected_points.get(week)


@dataclass(frozen=True)
class AdvisorTeamState:
    """One team's roster, FAAB, elimination and week projections.

    ``display_name`` is ``public.members.display_name`` -- the join key the rest
    of the platform matches on. ``member_label`` is what gets *rendered*:
    ``coalesce(nickname, sleeper_display_name, display_name)``, the league's one
    public label for a member. Nothing downstream should print ``display_name``.

    ``coverage_pct`` and ``is_provisional`` describe the *current* week, the one
    the gate is applied to. ``projected_points`` carries a week only when that
    week's own row cleared its gate, so a horizon week whose projections are
    still thin is absent rather than quietly shown.
    """

    team_id: int
    member_id: int
    display_name: str
    member_label: str
    team_name: str
    sleeper_roster_id: int
    faab_remaining: int
    is_eliminated: bool
    elimination_source: str | None
    week: int
    projected_points: Mapping[int, Decimal]
    coverage_pct: Decimal
    is_provisional: bool
    holdings: tuple[AdvisorHolding, ...]

    @property
    def projected_now(self) -> Decimal | None:
        """This week's team total, or ``None`` when it may not be shown."""
        return self.projected_points.get(self.week)

    def projected_for(self, week: int) -> Decimal | None:
        return self.projected_points.get(week)

    def starters(self) -> tuple[AdvisorHolding, ...]:
        return tuple(h for h in self.holdings if h.slot == "starter")

    def bench(self) -> tuple[AdvisorHolding, ...]:
        # `ir` and `taxi` holdings are deliberately not surplus: a team cannot
        # trade away what it is not allowed to start.
        return tuple(h for h in self.holdings if h.slot == "bench")


@dataclass(frozen=True)
class LeagueSnapshot:
    season: int
    season_id: int
    week: int
    #: Every week read, ``week`` first: the horizon, already capped.
    weeks: tuple[int, ...]
    #: The newest component stamp -- what to *display* as "last updated".
    synced_at: datetime
    #: The oldest component stamp -- what staleness is judged on.
    oldest_synced_at: datetime
    teams: tuple[AdvisorTeamState, ...]

    def team_for_member(self, member_id: int) -> AdvisorTeamState | None:
        return next((t for t in self.teams if t.member_id == member_id), None)

    def team_by_name(self, name: str) -> AdvisorTeamState | None:
        """Match a member by either the label the league renders or the join key.

        Case-insensitive, because the name arrives out of a text message and
        nobody types their own nickname the way the roster spells it. An
        *ambiguous* name -- two members whose label or join key both match -- is
        ``None`` too: guessing which of two managers a trade was meant for is
        worse than asking, and the caller cannot tell a guess from a match.
        """
        wanted = name.casefold()
        matches = [
            t
            for t in self.teams
            if t.member_label.casefold() == wanted or t.display_name.casefold() == wanted
        ]
        return matches[0] if len(matches) == 1 else None

    def player_names(self) -> dict[str, str]:
        return {h.sleeper_player_id: h.player_name for t in self.teams for h in t.holdings}

    def member_names(self) -> tuple[str, ...]:
        """The rendered label for every team, not the join key."""
        return tuple(t.member_label for t in self.teams)

    def coverage_ok(self) -> bool:
        """True when every non-eliminated team's projection may be shown."""
        return all(
            not t.is_provisional and t.coverage_pct >= COVERAGE_GATE
            for t in self.teams
            if not t.is_eliminated
        )

    def age(self, now: datetime) -> timedelta:
        """How old the *oldest* piece of this snapshot is -- see the module docstring."""
        return now - self.oldest_synced_at

    def is_stale(self, now: datetime) -> bool:
        return self.age(now) > STALE_AFTER


#: ``s.synced_at`` is selected raw, not coalesced: a team with no
#: ``team_season_state`` row has an unknown sync age, not an epoch-old one, and
#: :meth:`SnapshotRepository.load` refuses the snapshot rather than inventing a
#: timestamp. (SQL ``least``/``greatest`` skip nulls outright, which would erase
#: the missing component instead of reporting it, so the fold happens in Python.)
_TEAMS_SQL = """
select t.id, t.member_id, m.display_name,
       coalesce(m.nickname, m.sleeper_display_name, m.display_name),
       t.team_name, t.sleeper_roster_id,
       s.faab_remaining, coalesce(s.is_eliminated, false),
       s.elimination_source, s.synced_at
from public.teams t
join public.members m on m.id = t.member_id
left join public.team_season_state s on s.team_id = t.id and s.season_id = t.season_id
where t.season_id = %(season_id)s
order by t.id
"""

#: Every team-week row across the horizon. The current week's row supplies the
#: coverage gate; the later weeks supply the mapping a multi-week trade is judged on.
_TEAM_WEEKS_SQL = """
select team_id, week, projected_points, coverage_pct, is_provisional, computed_at
from public.team_week_projections
where season_id = %(season_id)s and week = any(%(weeks)s::int[])
order by team_id, week
"""

#: Live holdings for a live team, the frozen snapshot for an eliminated one.
#: The two arms are disjoint by construction -- ``live`` excludes an eliminated
#: team that has a ``final_rosters`` row, and ``frozen`` selects only those --
#: so no team can contribute a player twice however its rows happen to sit.
_HOLDINGS_SQL = """
with team_flags as (
    select t.id as team_id, coalesce(s.is_eliminated, false) as is_eliminated
    from public.teams t
    left join public.team_season_state s
      on s.team_id = t.id and s.season_id = t.season_id
    where t.season_id = %(season_id)s
),
frozen as (
    select f.team_id,
           entry.value ->> 'sleeper_player_id' as sleeper_player_id,
           entry.value ->> 'slot' as slot,
           (entry.value ->> 'slot_index')::int as slot_index,
           entry.value ->> 'lineup_position' as lineup_position,
           r.frozen_at as synced_at
    from team_flags f
    join public.final_rosters r on r.team_id = f.team_id and r.season_id = %(season_id)s
    cross join lateral jsonb_array_elements(r.holdings) as entry
    where f.is_eliminated
),
live as (
    select h.team_id, h.sleeper_player_id, h.slot, h.slot_index,
           h.lineup_position, h.synced_at
    from team_flags f
    join public.roster_holdings h on h.team_id = f.team_id and h.season_id = %(season_id)s
    where not f.is_eliminated
       or not exists (
              select 1 from public.final_rosters r
              where r.team_id = f.team_id and r.season_id = %(season_id)s
          )
),
held as (select * from frozen union all select * from live)
select held.team_id, held.sleeper_player_id,
       coalesce(pl.full_name, held.sleeper_player_id), pl.position,
       held.slot, held.lineup_position, held.slot_index, held.synced_at
from held
left join public.players pl on pl.sleeper_player_id = held.sleeper_player_id
order by held.team_id, held.slot, held.slot_index nulls last, held.sleeper_player_id
"""

#: Only the rostered players, only the horizon weeks, and only the rows that
#: actually carry a number: a null ``league_points`` is a missing projection, so
#: it is left out of the mapping instead of arriving as a zero.
_PLAYER_PROJECTIONS_SQL = """
select sleeper_player_id, week, league_points
from public.player_projections
where season = %(season)s
  and week = any(%(weeks)s::int[])
  and sleeper_player_id = any(%(player_ids)s::text[])
  and league_points is not null
"""


class SnapshotRepository:
    """Loads the whole league in six queries, once per advice run."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def load(self, horizon_weeks: int = 1) -> LeagueSnapshot:
        """Read one league week -- and optionally the weeks after it -- or say why not.

        The week comes from ``public.nfl_state`` through the same repository the
        sync writes it with, and it is gated on ``season_type == 'regular'``:
        preseason and postseason restart the week count from 1, so advising on a
        ``week`` that is not a regular-season week would run against the wrong
        slate entirely. Outside the regular season there is no week to advise on
        and this raises rather than guessing one.

        ``horizon_weeks`` is how many weeks of projections to carry, counting the
        current one, capped at :data:`LAST_REGULAR_WEEK`; the default of 1 reads
        this week alone. Only the *current* week's rows are required -- a horizon
        week nobody has computed yet is simply missing from the mappings, which
        is the ordinary state of the world on a Tuesday.
        """
        if horizon_weeks < 1:
            raise ValueError("horizon_weeks must be at least 1")

        state = NflStateRepository(self._conn).get()
        if state is None:
            raise SnapshotUnavailable("no public.nfl_state row")
        if state.season_type != "regular":
            raise SnapshotUnavailable(f"nfl_state season_type is {state.season_type!r}")
        season, week = state.season, state.week
        last = max(week, min(week + horizon_weeks - 1, LAST_REGULAR_WEEK))
        weeks = tuple(range(week, last + 1))

        with self._conn.cursor() as cur:
            cur.execute("select id from public.seasons where year = %s", (season,))
            season_row = cur.fetchone()
            if season_row is None:
                raise SnapshotUnavailable(f"no public.seasons row for {season}")
            season_id = season_row[0]

            params = {"season": season, "season_id": season_id, "weeks": list(weeks)}
            cur.execute(_TEAMS_SQL, params)
            team_rows = cur.fetchall()
            if not team_rows:
                raise SnapshotUnavailable(f"no teams for season {season}")

            cur.execute(_TEAM_WEEKS_SQL, params)
            team_week_rows = cur.fetchall()

            cur.execute(_HOLDINGS_SQL, params)
            holding_rows = cur.fetchall()

            player_ids = sorted({row[1] for row in holding_rows})
            cur.execute(_PLAYER_PROJECTIONS_SQL, {**params, "player_ids": player_ids})
            projection_rows = cur.fetchall()

        # Every stamp the snapshot is stitched from, folded once at the end into
        # the newest (displayed) and the oldest (what staleness is judged on).
        stamps: list[datetime] = [state.synced_at]

        points_by_player: dict[str, dict[int, Decimal]] = {}
        for player_id, projection_week, league_points in projection_rows:
            points_by_player.setdefault(player_id, {})[projection_week] = league_points

        holdings_by_team: dict[int, list[AdvisorHolding]] = {}
        for row in holding_rows:
            holdings_by_team.setdefault(row[0], []).append(
                AdvisorHolding(
                    sleeper_player_id=row[1],
                    player_name=row[2],
                    position=row[3],
                    slot=row[4],
                    lineup_position=row[5],
                    slot_index=row[6],
                    week=week,
                    projected_points=MappingProxyType(
                        dict(points_by_player.get(row[1], {}))
                    ),
                )
            )
            stamps.append(row[7])

        team_weeks: dict[int, dict[int, tuple[Decimal, Decimal, bool, datetime]]] = {}
        for team_id, row_week, points, coverage, provisional, computed_at in team_week_rows:
            team_weeks.setdefault(team_id, {})[row_week] = (
                points,
                coverage,
                bool(provisional),
                computed_at,
            )

        teams: list[AdvisorTeamState] = []
        for row in team_rows:
            team_id = row[0]
            if row[9] is None:
                raise SnapshotUnavailable(
                    f"no public.team_season_state row for team {team_id}"
                )
            stamps.append(row[9])

            by_week = team_weeks.get(team_id, {})
            current = by_week.get(week)
            if current is None:
                raise SnapshotUnavailable(
                    f"no public.team_week_projections row for team {team_id} week {week}"
                )
            stamps.append(current[3])

            # A provisional week's number must never be shown, so it is not even
            # carried: nothing downstream can leak what it does not have.
            projected = {
                w: points
                for w, (points, _coverage, provisional, _at) in sorted(by_week.items())
                if not provisional and points is not None
            }
            teams.append(
                AdvisorTeamState(
                    team_id=team_id,
                    member_id=row[1],
                    display_name=row[2],
                    member_label=row[3],
                    team_name=row[4],
                    sleeper_roster_id=row[5],
                    faab_remaining=int(row[6]),
                    is_eliminated=bool(row[7]),
                    elimination_source=row[8],
                    week=week,
                    projected_points=MappingProxyType(projected) if projected else _NO_POINTS,
                    coverage_pct=current[1],
                    is_provisional=current[2],
                    holdings=tuple(holdings_by_team.get(team_id, ())),
                )
            )

        return LeagueSnapshot(
            season=season,
            season_id=season_id,
            week=week,
            weeks=weeks,
            synced_at=max(stamps),
            oldest_synced_at=min(stamps),
            teams=tuple(teams),
        )
