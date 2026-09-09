"""Fetch, score, and store one NFL week of Sleeper player projections.

The raw stat map is kept verbatim so a scoring change can be replayed without
refetching, and so a wrong scoring rule is a bug that can be corrected rather
than data that has to be re-downloaded.

The writes here take a connection and never open a transaction of their own:
Task 10 runs this and the team-week recompute inside one ``conn.transaction()``,
so a week's player rows and the team totals derived from them land together or
not at all.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

import psycopg
from psycopg.types.json import Jsonb

from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.scoring import (
    CENTS,
    DRIFT_POINTS,
    DRIFT_SHARE,
    preset_drift,
    score_stat_line,
    scoring_version,
)
from ultimate_guillotine.sleeper.state import NflState, current_week

#: A live week has roughly 9,400 rows. Anything under this is a broken payload, not a
#: quiet week, and writing it would zero out a week that already had good numbers.
MIN_PROJECTION_ROWS = 200

#: Drift shares are reported to four places; points and dollars keep ``CENTS``.
_DRIFT_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True)
class ProjectionRow:
    sleeper_player_id: str
    stat_line: dict[str, float]
    pts_ppr: Decimal | None
    pts_half_ppr: Decimal | None
    pts_std: Decimal | None
    projected_at: datetime


@dataclass(frozen=True)
class ProjectionReport:
    rows: int
    scored: int
    unscored: int
    scoring_version: str
    drift_share: Decimal
    drift_flagged: bool


def _preset(stats: dict[str, object], key: str) -> Decimal | None:
    value = stats.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def _projected_at(record: dict[str, object], now: datetime) -> datetime:
    """Sleeper timestamps projections in epoch milliseconds."""
    for key in ("updated_at", "last_modified"):
        raw = record.get(key)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
            return datetime.fromtimestamp(float(raw) / 1000.0, tz=UTC)
    return now


def load_projections(
    payload: list[dict[str, object]], week: int, now: datetime
) -> list[ProjectionRow]:
    """Parse the recorded projections shape into rows, dropping anything off-week."""
    rows: list[ProjectionRow] = []
    for record in payload:
        if not isinstance(record, dict) or record.get("category") != "proj":
            continue
        player_id = record.get("player_id")
        stats = record.get("stats")
        if not isinstance(player_id, str) or not player_id:
            continue
        if not isinstance(stats, dict) or not stats:
            continue
        record_week = record.get("week")
        if isinstance(record_week, int) and record_week != week:
            continue
        numeric = {
            key: float(value)
            for key, value in stats.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        if not numeric:
            continue
        rows.append(
            ProjectionRow(
                sleeper_player_id=player_id,
                stat_line=numeric,
                pts_ppr=_preset(stats, "pts_ppr"),
                pts_half_ppr=_preset(stats, "pts_half_ppr"),
                pts_std=_preset(stats, "pts_std"),
                projected_at=_projected_at(record, now),
            )
        )
    return rows


def projection_week(state: NflState) -> tuple[int, int]:
    """The ``(season, week)`` to project, or a refusal.

    ``NflState.week`` restarts inside each season type, so a preseason or
    postseason week number is not a regular-season week and there is no
    regular-season slate to project. Refusing here is the whole point: writing
    preseason numbers into ``player_projections`` would look exactly like a real
    week to everything downstream.
    """
    if state.season_type != "regular":
        raise RuntimeError(
            f"nfl_state is in the {state.season_type} season, not the regular season: "
            "there is no week to project"
        )
    return state.season, state.week


def _report(
    scored_points: list[Decimal | None], lines: list[dict[str, float]], version: str
) -> ProjectionReport:
    scored = [p for p in scored_points if p is not None]
    drifted = 0
    compared = 0
    for points, line in zip(scored_points, lines, strict=True):
        drift = preset_drift(points, line)
        if drift is None:
            continue
        compared += 1
        if drift > DRIFT_POINTS:
            drifted += 1
    share = Decimal(drifted) / Decimal(compared) if compared else Decimal(0)
    return ProjectionReport(
        rows=len(scored_points),
        scored=len(scored),
        unscored=len(scored_points) - len(scored),
        scoring_version=version,
        drift_share=share.quantize(_DRIFT_QUANTUM, rounding=ROUND_HALF_UP),
        drift_flagged=share > DRIFT_SHARE,
    )


class ProjectionRepository:
    """Row-level writes against ``public.player_projections``.

    Every method runs on the caller's connection and inside the caller's
    transaction; none of them commit.
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def upsert_many(
        self,
        season: int,
        week: int,
        rows: list[ProjectionRow],
        scoring_settings: dict[str, object],
        version: str,
        now: datetime,
    ) -> ProjectionReport:
        """Write one week of scored rows. ``league_points`` is null, never zero, when
        the league's settings cannot score a stat line."""
        points = [score_stat_line(r.stat_line, scoring_settings) for r in rows]
        with self._conn.cursor() as cur:
            cur.executemany(
                """
                insert into public.player_projections
                  (season, week, sleeper_player_id, stat_line, league_points, pts_ppr,
                   pts_half_ppr, pts_std, scoring_version, source, coverage_flagged,
                   run_coverage_pct, projected_at, synced_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'sleeper', false, null, %s, %s)
                on conflict (season, week, sleeper_player_id) do update set
                  stat_line = excluded.stat_line, league_points = excluded.league_points,
                  pts_ppr = excluded.pts_ppr, pts_half_ppr = excluded.pts_half_ppr,
                  pts_std = excluded.pts_std, scoring_version = excluded.scoring_version,
                  source = excluded.source, coverage_flagged = false,
                  run_coverage_pct = null, projected_at = excluded.projected_at,
                  synced_at = excluded.synced_at
                """,
                [
                    (
                        season,
                        week,
                        row.sleeper_player_id,
                        Jsonb(row.stat_line),
                        value,
                        row.pts_ppr,
                        row.pts_half_ppr,
                        row.pts_std,
                        version,
                        row.projected_at,
                        now,
                    )
                    for row, value in zip(rows, points, strict=True)
                ],
            )
        return _report(points, [r.stat_line for r in rows], version)

    def rescore(
        self,
        season: int,
        week: int,
        scoring_settings: dict[str, object],
        version: str,
        now: datetime,
    ) -> ProjectionReport:
        """Recompute points from stored stat lines. No network call."""
        with self._conn.cursor() as cur:
            cur.execute(
                "select sleeper_player_id, stat_line from public.player_projections "
                "where season = %s and week = %s order by sleeper_player_id",
                (season, week),
            )
            stored = cur.fetchall()
            points = [score_stat_line(line, scoring_settings) for _pid, line in stored]
            cur.executemany(
                """
                update public.player_projections
                set league_points = %s, scoring_version = %s, synced_at = %s
                where season = %s and week = %s and sleeper_player_id = %s
                """,
                [
                    (value, version, now, season, week, pid)
                    for (pid, _line), value in zip(stored, points, strict=True)
                ],
            )
        return _report(points, [line for _pid, line in stored], version)

    def flag_coverage(
        self, season: int, week: int, run_coverage_pct: Decimal, flagged: bool
    ) -> None:
        """Stamp the run's coverage on every row it wrote. Flagged, never withheld."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                update public.player_projections
                set coverage_flagged = %s, run_coverage_pct = %s
                where season = %s and week = %s
                """,
                (flagged, run_coverage_pct, season, week),
            )


def sync_projections(
    client: SleeperClient,
    conn: psycopg.Connection,
    season: int,
    week: int,
    scoring_settings: dict[str, object],
    now: datetime,
    rescore: bool = False,
) -> ProjectionReport:
    """Fetch (or reuse) a week of projections, score them, and upsert.

    The caller owns the transaction. This function writes on ``conn`` and never
    opens or commits one of its own, so Task 10 can wrap it and the team-week
    recompute in a single ``conn.transaction()`` and have the two land together.

    ``rescore`` skips the fetch entirely: the stat lines are already stored, and
    a scoring change is not a reason to ask Sleeper for the same numbers again.
    """
    version = scoring_version(scoring_settings)
    repo = ProjectionRepository(conn)
    if rescore:
        return repo.rescore(season, week, scoring_settings, version, now)
    rows = load_projections(client.get_projections(season, week), week, now)
    if len(rows) < MIN_PROJECTION_ROWS:
        # Refuse before touching the table: a 200 with no body must never zero out a
        # week that already has good projections, and the caller's transaction may be
        # carrying other work that should not be rolled back over this.
        raise RuntimeError(
            f"sleeper returned too few projections for {season} week {week}: {len(rows)}"
        )
    return repo.upsert_many(season, week, rows, scoring_settings, version, now)


def sync_current_week_projections(
    client: SleeperClient,
    conn: psycopg.Connection,
    scoring_settings: dict[str, object],
    now: datetime,
    rescore: bool = False,
) -> ProjectionReport:
    """Sync the week ``public.nfl_state`` reports, refusing anything but the regular season.

    The season and week are read from state rather than passed in, so a scheduled
    run cannot drift onto a week the league is not actually playing. The state read
    happens before the fetch, so a preseason run costs nothing and writes nothing.
    """
    season, week = projection_week(current_week(client, conn, now))
    return sync_projections(client, conn, season, week, scoring_settings, now, rescore=rescore)
