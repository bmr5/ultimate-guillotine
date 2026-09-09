"""Team projected points for one week, and the 95 percent coverage gate.

An empty starter slot and a missing projection both add zero points, and the
difference between them is the whole point of this module: nobody can project a
slot a manager left blank, so it does not count against coverage, while a filled
slot with no projection does.

A filled slot counts as projected only when its ``player_projections`` row carries
a non-null ``league_points``. A null is a missing projection, never a zero: Task 8
nulls the points of a player who left the feed rather than deleting his row, so
reading null as zero would quietly drag a team's total down and still report full
coverage.

The starter-slot count comes from ``public.seasons.roster_positions`` and the
filled slots from ``public.roster_holdings`` -- both read here, from the database,
rather than carried over from the Sleeper payload the sync parsed.

Every write runs on the caller's connection and inside the caller's transaction;
nothing here opens or commits one of its own, so Task 10 can wrap Task 8's player
write and this recompute in a single ``conn.transaction()`` and have a week's
player rows and the team totals derived from them land together or not at all.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

import psycopg

#: Below this, a team's number is not shown: consumers render "projection unavailable".
COVERAGE_GATE = Decimal(95)

_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class StarterTally:
    team_id: int
    filled_slots: int
    starters_projected: int
    projected_points: Decimal
    is_eliminated: bool


@dataclass(frozen=True)
class TeamWeekProjection:
    team_id: int
    projected_points: Decimal
    starter_slots: int
    filled_slots: int
    empty_slots: int
    starters_projected: int
    missing_projections: int
    coverage_pct: Decimal
    is_provisional: bool


def coverage_pct(starters_projected: int, filled_slots: int) -> Decimal:
    """Share of filled starter slots that carry a projection.

    A roster with nothing in its starting lineup is fully covered, not zero
    covered: there is nothing left to project.
    """
    if filled_slots <= 0:
        return Decimal("100.00")
    share = Decimal(starters_projected) / Decimal(filled_slots) * Decimal(100)
    return share.quantize(_CENTS, rounding=ROUND_HALF_UP)


def run_coverage(tallies: list[StarterTally]) -> Decimal:
    """One coverage number for the whole run, over non-eliminated teams only.

    An eliminated team's lineup stops being maintained the week it goes out, so
    counting its unprojected starters would fail the gate for the whole league
    over rosters nobody is going to read. It still gets its own row.
    """
    live = [t for t in tallies if not t.is_eliminated]
    filled = sum(t.filled_slots for t in live)
    projected = sum(t.starters_projected for t in live)
    return coverage_pct(projected, filled)


def build_team_week(
    tallies: list[StarterTally], starter_slots: int, run_pct: Decimal
) -> list[TeamWeekProjection]:
    """Turn tallies into rows. A failing run gate makes every row provisional.

    ``is_provisional`` is ``coverage_pct < 95 or run_coverage_pct < 95`` -- the
    plan's resolution to Spec issue 4. A run-wide projection failure is not
    something one team escapes, eliminated teams included: they are left out of
    the run's arithmetic, not shielded from its verdict.
    """
    run_failed = run_pct < COVERAGE_GATE
    rows: list[TeamWeekProjection] = []
    for tally in tallies:
        team_pct = coverage_pct(tally.starters_projected, tally.filled_slots)
        rows.append(
            TeamWeekProjection(
                team_id=tally.team_id,
                projected_points=tally.projected_points.quantize(
                    _CENTS, rounding=ROUND_HALF_UP
                ),
                starter_slots=starter_slots,
                filled_slots=tally.filled_slots,
                empty_slots=max(starter_slots - tally.filled_slots, 0),
                starters_projected=tally.starters_projected,
                missing_projections=tally.filled_slots - tally.starters_projected,
                coverage_pct=team_pct,
                is_provisional=team_pct < COVERAGE_GATE or run_failed,
            )
        )
    return rows


class TeamWeekRepository:
    """Reads and writes for one week of team projections.

    Every method runs on the caller's connection and inside the caller's
    transaction; none of them commit.
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def starter_slots(self, season_id: int) -> int:
        """How many starting slots the league runs, per the cached roster positions."""
        with self._conn.cursor() as cur:
            cur.execute(
                "select jsonb_array_length(roster_positions) from public.seasons "
                "where id = %s",
                (season_id,),
            )
            row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def tally(self, season_id: int, season_year: int, week: int) -> list[StarterTally]:
        """Per team: filled starter slots, how many are projected, and their sum.

        ``count(p.league_points)`` counts non-null points, so a starter whose row
        exists with null points is counted as missing, exactly like one with no
        row at all. The projections join is keyed on the plain season year,
        because a projection is a property of the NFL week, not of this league.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select t.id,
                       count(h.sleeper_player_id) as filled,
                       count(p.league_points) as projected,
                       coalesce(sum(p.league_points), 0) as points,
                       coalesce(bool_or(s.is_eliminated), false) as eliminated
                from public.teams t
                left join public.roster_holdings h
                  on h.team_id = t.id and h.season_id = t.season_id
                     and h.slot = 'starter'
                left join public.player_projections p
                  on p.sleeper_player_id = h.sleeper_player_id
                     and p.season = %s and p.week = %s
                left join public.team_season_state s
                  on s.team_id = t.id and s.season_id = t.season_id
                where t.season_id = %s
                group by t.id
                order by t.id
                """,
                (season_year, week, season_id),
            )
            return [StarterTally(*row) for row in cur.fetchall()]

    def upsert_many(
        self, season_id: int, week: int, rows: list[TeamWeekProjection], now: datetime
    ) -> int:
        """Write one row per team for the week, replacing the last run's numbers."""
        with self._conn.cursor() as cur:
            cur.executemany(
                """
                insert into public.team_week_projections
                  (season_id, team_id, week, projected_points, starter_slots,
                   filled_slots, empty_slots, starters_projected, missing_projections,
                   coverage_pct, is_provisional, computed_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (season_id, team_id, week) do update set
                  projected_points = excluded.projected_points,
                  starter_slots = excluded.starter_slots,
                  filled_slots = excluded.filled_slots,
                  empty_slots = excluded.empty_slots,
                  starters_projected = excluded.starters_projected,
                  missing_projections = excluded.missing_projections,
                  coverage_pct = excluded.coverage_pct,
                  is_provisional = excluded.is_provisional,
                  computed_at = excluded.computed_at
                """,
                [
                    (season_id, r.team_id, week, r.projected_points, r.starter_slots,
                     r.filled_slots, r.empty_slots, r.starters_projected,
                     r.missing_projections, r.coverage_pct, r.is_provisional, now)
                    for r in rows
                ],
            )
        return len(rows)


def recompute_team_week(
    conn: psycopg.Connection, season_id: int, season_year: int, week: int, now: datetime
) -> tuple[list[TeamWeekProjection], Decimal]:
    """Recompute every team's week row and return the rows plus the run's coverage.

    Writes on ``conn`` inside the caller's transaction and never opens one of its
    own. Rerunning it for the same ``(season_id, week)`` rewrites the same rows.
    """
    repo = TeamWeekRepository(conn)
    tallies = repo.tally(season_id, season_year, week)
    run_pct = run_coverage(tallies)
    rows = build_team_week(tallies, repo.starter_slots(season_id), run_pct)
    repo.upsert_many(season_id, week, rows, now)
    return rows, run_pct
