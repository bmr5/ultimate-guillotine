"""Fetch, score, and store one NFL week of Sleeper player projections.

The raw stat map is kept verbatim so a scoring change can be replayed without
refetching, and so a wrong scoring rule is a bug that can be corrected rather
than data that has to be re-downloaded.

The writes here take a connection and never open a transaction of their own.
``ug sleeper projections`` is the only caller: it fetches first, then runs the
upsert, the team-week recompute, and the coverage stamp inside one
``conn.transaction()``, so a week's player rows and the team totals derived from
them land together or not at all.

**A player who leaves the feed keeps his row and loses his points.** A sync never
deletes: any stored row of the same ``(season, week)`` that this run's payload did
not carry has ``league_points`` set to null in the same transaction as the upsert.
Deleting would make a vanished player indistinguishable from one who was never
there, and leaving the old number standing would let a stale projection be read as
this run's. Null is the honest third answer: the row and its stat line stay, and
downstream counts the player as missing rather than as zero. ``synced_at`` is left
at the run that last carried him, so how stale the row is stays legible.
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
)

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


@dataclass(frozen=True)
class WeekFlags:
    """The flagged state a week is already in, read before a run overwrites it.

    The ops notes fire on the edges, so a run has to know what the last one left
    behind. Coverage is a stored column; drift is not stored, and is re-derived
    from the rows themselves -- see :meth:`ProjectionRepository.week_flags`.
    """

    coverage_flagged: bool
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


def _drift(
    scored_points: list[Decimal | None], lines: list[dict[str, float]]
) -> tuple[Decimal, bool]:
    """The share of scored players far from every Sleeper preset, and the verdict.

    Split out of :func:`_report` so the same rule can be applied to rows already
    in the table, which is how the previous run's drift verdict is recovered
    without storing it.
    """
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
    return share.quantize(_DRIFT_QUANTUM, rounding=ROUND_HALF_UP), share > DRIFT_SHARE


def _report(
    scored_points: list[Decimal | None], lines: list[dict[str, float]], version: str
) -> ProjectionReport:
    scored = [p for p in scored_points if p is not None]
    share, flagged = _drift(scored_points, lines)
    return ProjectionReport(
        rows=len(scored_points),
        scored=len(scored),
        unscored=len(scored_points) - len(scored),
        scoring_version=version,
        drift_share=share,
        drift_flagged=flagged,
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
        """Write one week of scored rows, and null the points of the ones that left.

        ``league_points`` is null, never zero, when the league's settings cannot
        score a stat line. Stored rows of this ``(season, week)`` that this run's
        payload did not carry are not deleted: their ``league_points`` is set to
        null in the same transaction, so downstream reads them as missing rather
        than as a stale number. Their ``synced_at`` is left at the run that last
        carried them.
        """
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
            cur.execute(
                """
                update public.player_projections
                set league_points = null
                where season = %s and week = %s
                  and not (sleeper_player_id = any(%s))
                  and league_points is not null
                """,
                (season, week, [row.sleeper_player_id for row in rows]),
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
        """Rescore every stored row of the week from its stat line. No network call.

        Only ``league_points`` and ``scoring_version`` change. ``synced_at`` is left
        alone: a rescore is not a sync, nothing was refetched, and moving the stamp
        would make a week of untouched numbers look freshly pulled from Sleeper.

        Refuses a week with no stored rows — there is nothing to rescore, and
        silently reporting zero rows would read as a successful replay.

        ``now`` is accepted so the signature matches ``upsert_many`` and the caller
        need not know which path it is on; it is deliberately unused.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                "select sleeper_player_id, stat_line from public.player_projections "
                "where season = %s and week = %s order by sleeper_player_id",
                (season, week),
            )
            stored = cur.fetchall()
            if not stored:
                raise RuntimeError(f"no stored projections for {season} week {week}")
            points = [score_stat_line(line, scoring_settings) for _pid, line in stored]
            cur.executemany(
                """
                update public.player_projections
                set league_points = %s, scoring_version = %s
                where season = %s and week = %s and sleeper_player_id = %s
                """,
                [
                    (value, version, season, week, pid)
                    for (pid, _line), value in zip(stored, points, strict=True)
                ],
            )
        return _report(points, [line for _pid, line in stored], version)

    def week_flags(self, season: int, week: int) -> WeekFlags:
        """The flagged state the week is currently in, as the last run left it.

        Coverage is a stored column, stamped on every row of the week by
        :meth:`flag_coverage`. Drift is not stored, and does not need to be: the
        stored ``league_points`` and ``stat_line`` are precisely what the last run
        scored, so re-running the drift rule over them recovers that run's verdict
        exactly. A week with no rows yet is clear on both counts, so the first
        flagged run of a week reads as a transition and says so once.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                "select coverage_flagged, league_points, stat_line "
                "from public.player_projections where season = %s and week = %s",
                (season, week),
            )
            rows = cur.fetchall()
        if not rows:
            return WeekFlags(coverage_flagged=False, drift_flagged=False)
        _share, drift_flagged = _drift(
            [points for _flag, points, _line in rows],
            [line for _flag, _points, line in rows],
        )
        return WeekFlags(
            coverage_flagged=any(flag for flag, _points, _line in rows),
            drift_flagged=drift_flagged,
        )

    def flag_coverage(
        self, season: int, week: int, run_coverage_pct: Decimal, flagged: bool
    ) -> int:
        """Stamp the run's coverage on every row it wrote. Flagged, never withheld.

        Bounded by what would actually change: this job fires every five minutes
        through a game window and the stamp is usually the same one it wrote last
        time, so an unbounded update would rewrite ~9,400 unchanged rows a run --
        dead tuples for the vacuum, and a write-heavy replication stream saying
        nothing. ``is distinct from`` rather than ``<>`` because ``run_coverage_pct``
        is null on every row an upsert just wrote. Returns how many rows moved.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                update public.player_projections
                set coverage_flagged = %s, run_coverage_pct = %s
                where season = %s and week = %s
                  and (coverage_flagged is distinct from %s
                       or run_coverage_pct is distinct from %s)
                """,
                (flagged, run_coverage_pct, season, week, flagged, run_coverage_pct),
            )
            return cur.rowcount


def fetch_projection_rows(
    client: SleeperClient, season: int, week: int, now: datetime
) -> list[ProjectionRow]:
    """Fetch and parse one week of projections, refusing a payload too thin to be real.

    Touches no database, so the caller can fetch *before* opening its transaction:
    a 200 with no body is the likeliest failure of the whole command, and it should
    abort the run rather than roll back a transaction that had already begun
    writing.
    """
    rows = load_projections(client.get_projections(season, week), week, now)
    if len(rows) < MIN_PROJECTION_ROWS:
        # A 200 with no body must never zero out a week that already has good
        # projections, so this refuses before anything is written at all.
        raise RuntimeError(
            f"sleeper returned too few projections for {season} week {week}: {len(rows)}"
        )
    return rows
