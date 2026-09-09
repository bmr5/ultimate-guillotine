import type { TableRow } from "../types";

/**
 * The `public.weekly_results` columns the board reads. Structurally the same row the typed
 * `Database` describes, minus the identity and season keys the aggregation never looks at, so
 * a drifted column name still fails `tsc` at the call site.
 */
export type WeeklyResultRow = Pick<
  TableRow<"weekly_results">,
  "week" | "team_id" | "points" | "is_final" | "state_version"
>;

/** Points are stored as postgres `numeric`; two decimals is the widest a scored week uses. */
export const POINTS_DECIMALS = 2;

const POINTS_ROUNDING_FACTOR = 10 ** POINTS_DECIMALS;

/**
 * `public.weekly_results` has no opponent or matchup column, so a win/loss record cannot be
 * derived from it — that comes from `public.team_season_state`. This produces the points-for
 * fallback used when a team has no state row yet.
 */
export interface TeamPointsSummary {
  pointsFor: number;
  /**
   * The highest week this team has a final row for. `latestFinalWeek` folds it across the
   * league to give the board a real week to scope to once `nfl_state` has left the regular
   * season and its own `week` no longer names a week the league played.
   */
  lastFinalWeek: number | null;
}

/** A corrected week leaves both state_versions in the table; this key picks the newest. */
function teamWeekKey(row: WeeklyResultRow): string {
  return `${row.team_id}:${row.week}`;
}

/**
 * Float addition drifts (`0.1 + 0.2`), and the board renders the sum, so each running total is
 * snapped back to the precision the column actually carries.
 */
function addPoints(total: number, points: number): number {
  return (
    Math.round((total + points) * POINTS_ROUNDING_FACTOR) /
    POINTS_ROUNDING_FACTOR
  );
}

export function summarizeWeeklyResults(
  rows: readonly WeeklyResultRow[],
): Map<number, TeamPointsSummary> {
  // Keep the newest row per team-week first, then filter: a correction that reopens a week
  // must remove the superseded final row from the total rather than leaving it stranded.
  const newest = new Map<string, WeeklyResultRow>();
  for (const row of rows) {
    const key = teamWeekKey(row);
    const existing = newest.get(key);
    if (existing === undefined || row.state_version > existing.state_version) {
      newest.set(key, row);
    }
  }

  const summaries = new Map<number, TeamPointsSummary>();
  for (const row of newest.values()) {
    if (!row.is_final) {
      continue;
    }
    const current = summaries.get(row.team_id) ?? {
      pointsFor: 0,
      lastFinalWeek: null,
    };
    summaries.set(row.team_id, {
      pointsFor: addPoints(current.pointsFor, row.points),
      lastFinalWeek:
        current.lastFinalWeek === null
          ? row.week
          : Math.max(current.lastFinalWeek, row.week),
    });
  }
  return summaries;
}

/**
 * The newest week the league has a final result for, or `null` when it has none.
 *
 * The board is scoped to `nfl_state.week`, which is the right week right up until the regular
 * season ends: in the post-season and the offseason that number names a week this league never
 * played, so every week-scoped query filters to nothing and the board goes blank. This is the
 * week it falls back to — the last one that actually has rows — folded from the same corrected,
 * deduplicated summaries the points-for column is built from.
 */
export function latestFinalWeek(
  rows: readonly WeeklyResultRow[],
): number | null {
  let latest: number | null = null;
  for (const summary of summarizeWeeklyResults(rows).values()) {
    if (summary.lastFinalWeek === null) {
      continue;
    }
    latest =
      latest === null
        ? summary.lastFinalWeek
        : Math.max(latest, summary.lastFinalWeek);
  }
  return latest;
}
