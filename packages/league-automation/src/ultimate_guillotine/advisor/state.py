"""One read of the league data layer, cached for the length of one advice run.

The Advisor reads rosters, projections, FAAB and elimination once per run and
reuses that snapshot for every candidate: a run that re-queried per candidate
would be both slow and internally inconsistent, proposing a trade against two
different versions of the same roster.

Every table here belongs to the league data layer spec. Nothing in this module
writes, and nothing here invents a number: a null ``league_points`` stays
``None`` all the way to the formatter, because a missing projection is not a
zero. Below the coverage gate the projection is withheld outright, which is
what the data layer requires of every consumer.

The dataclasses are named ``Advisor*`` on purpose. ``sleeper.roster_state``
already owns a ``Holding`` and a ``TeamState``, and those are *write* shapes --
what one Sleeper payload classified into. These are *read* shapes: a holding
here carries the player's name and his projected points, which the sync's
holding never does. Two different things with one name in two modules is how a
later import lands on the wrong one silently, so they keep different names.

**An eliminated team's holdings come from its frozen roster when it has one.**
``public.roster_holdings`` is current-state only and a manager who is out goes
on dropping and adding, so reading it would offer trades over players the team
did not go out with. ``public.final_rosters.holdings`` is the roster it was
eliminated with, written once and never rewritten, and that is what an
eliminated team shows here. A team marked eliminated by hand and never synced
since has no frozen snapshot, and falls back to its live holdings -- the same
precedence ``sleeper.team_projections`` applies to the projection arithmetic.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg

from ultimate_guillotine.sleeper.state import NflStateRepository
from ultimate_guillotine.sleeper.team_projections import COVERAGE_GATE

#: The data layer's staleness window: past this the Advisor reports the age of
#: what it has instead of advising from it.
STALE_AFTER = timedelta(minutes=30)

__all__ = [
    "COVERAGE_GATE",
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
    """One rostered player, with the name and the number the Advisor renders."""

    sleeper_player_id: str
    player_name: str
    position: str | None
    slot: str
    lineup_position: str | None
    slot_index: int | None
    projected_points: float | None


@dataclass(frozen=True)
class AdvisorTeamState:
    """One team's roster, FAAB, elimination and week projection.

    ``display_name`` is ``public.members.display_name`` -- the join key the rest
    of the platform matches on. ``member_label`` is what gets *rendered*:
    ``coalesce(nickname, sleeper_display_name, display_name)``, the league's one
    public label for a member. Nothing downstream should print ``display_name``.
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
    projected_points: float | None
    coverage_pct: float
    is_provisional: bool
    holdings: tuple[AdvisorHolding, ...]

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
    synced_at: datetime
    teams: tuple[AdvisorTeamState, ...]

    def team_for_member(self, member_id: int) -> AdvisorTeamState | None:
        return next((t for t in self.teams if t.member_id == member_id), None)

    def team_by_name(self, name: str) -> AdvisorTeamState | None:
        """Match a member by either the label the league renders or the join key.

        Case-insensitive, because the name arrives out of a text message and
        nobody types their own nickname the way the roster spells it.
        """
        wanted = name.casefold()
        return next(
            (
                t
                for t in self.teams
                if t.member_label.casefold() == wanted or t.display_name.casefold() == wanted
            ),
            None,
        )

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
        return now - self.synced_at

    def is_stale(self, now: datetime) -> bool:
        return self.age(now) > STALE_AFTER


_TEAMS_SQL = """
select t.id, t.member_id, m.display_name,
       coalesce(m.nickname, m.sleeper_display_name, m.display_name),
       t.team_name, t.sleeper_roster_id,
       coalesce(s.faab_remaining, 0), coalesce(s.is_eliminated, false),
       s.elimination_source, p.projected_points, coalesce(p.coverage_pct, 0),
       coalesce(p.is_provisional, true),
       greatest(coalesce(s.synced_at, 'epoch'::timestamptz),
                coalesce(p.computed_at, 'epoch'::timestamptz))
from public.teams t
join public.members m on m.id = t.member_id
left join public.team_season_state s on s.team_id = t.id and s.season_id = t.season_id
left join public.team_week_projections p
       on p.team_id = t.id and p.season_id = t.season_id and p.week = %(week)s
where t.season_id = %(season_id)s
order by t.id
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
       held.slot, held.lineup_position, held.slot_index, pr.league_points, held.synced_at
from held
left join public.players pl on pl.sleeper_player_id = held.sleeper_player_id
left join public.player_projections pr
       on pr.sleeper_player_id = held.sleeper_player_id
      and pr.season = %(season)s and pr.week = %(week)s
order by held.team_id, held.slot, held.slot_index nulls last, held.sleeper_player_id
"""


class SnapshotRepository:
    """Loads the whole league in four queries, once per advice run."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def load(self) -> LeagueSnapshot:
        """Read one week of the data layer, or say why it cannot be read.

        The week comes from ``public.nfl_state`` through the same repository the
        sync writes it with, and it is gated on ``season_type == 'regular'``:
        preseason and postseason restart the week count from 1, so advising on a
        ``week`` that is not a regular-season week would run against the wrong
        slate entirely. Outside the regular season there is no week to advise on
        and this raises rather than guessing one.
        """
        state = NflStateRepository(self._conn).get()
        if state is None:
            raise SnapshotUnavailable("no public.nfl_state row")
        if state.season_type != "regular":
            raise SnapshotUnavailable(f"nfl_state season_type is {state.season_type!r}")
        season, week = state.season, state.week

        with self._conn.cursor() as cur:
            cur.execute("select id from public.seasons where year = %s", (season,))
            season_row = cur.fetchone()
            if season_row is None:
                raise SnapshotUnavailable(f"no public.seasons row for {season}")
            season_id = season_row[0]

            params = {"season": season, "season_id": season_id, "week": week}
            cur.execute(_TEAMS_SQL, params)
            team_rows = cur.fetchall()
            if not team_rows:
                raise SnapshotUnavailable(f"no teams for season {season}")

            cur.execute(_HOLDINGS_SQL, params)
            holding_rows = cur.fetchall()

        by_team: dict[int, list[AdvisorHolding]] = {}
        newest = state.synced_at
        for row in holding_rows:
            by_team.setdefault(row[0], []).append(
                AdvisorHolding(
                    sleeper_player_id=row[1],
                    player_name=row[2],
                    position=row[3],
                    slot=row[4],
                    lineup_position=row[5],
                    slot_index=row[6],
                    projected_points=float(row[7]) if row[7] is not None else None,
                )
            )
            newest = max(newest, row[8])

        teams: list[AdvisorTeamState] = []
        for row in team_rows:
            provisional = bool(row[11])
            teams.append(
                AdvisorTeamState(
                    team_id=row[0],
                    member_id=row[1],
                    display_name=row[2],
                    member_label=row[3],
                    team_name=row[4],
                    sleeper_roster_id=row[5],
                    faab_remaining=int(row[6]),
                    is_eliminated=bool(row[7]),
                    elimination_source=row[8],
                    # A provisional team's number must never be shown, so it is
                    # not even carried: nothing downstream can leak what it does
                    # not have.
                    projected_points=None if provisional or row[9] is None else float(row[9]),
                    coverage_pct=float(row[10]),
                    is_provisional=provisional,
                    holdings=tuple(by_team.get(row[0], ())),
                )
            )
            newest = max(newest, row[12])

        return LeagueSnapshot(
            season=season,
            season_id=season_id,
            week=week,
            synced_at=newest,
            teams=tuple(teams),
        )
