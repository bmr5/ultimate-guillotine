import type { SeasonScoreRow } from "../fetchers";

export interface SeasonPoints {
  total: number;
  /** How many weeks' rows named the player — the caption's honest denominator. */
  weeks: number;
}

/**
 * The player's points over the weeks he was on any roster, from `team_week_scores`.
 *
 * With nine roster slots and no bench, every rostered player is a starter and every week's
 * row names him, so this is the season to date for the weeks he was in the league. A week he
 * sat unrostered is a gap the caption owns up to rather than a zero. One value per week: a
 * player who appears in two teams' rows for one week — a trade mid-sync — counts once.
 */
export function seasonPoints(
  rows: readonly SeasonScoreRow[],
  sleeperPlayerId: string,
): SeasonPoints {
  const byWeek = new Map<number, number>();
  for (const row of rows) {
    const value: unknown = row.players_points?.[sleeperPlayerId];
    if (typeof value !== "number" || !Number.isFinite(value)) continue;
    if (!byWeek.has(row.week)) byWeek.set(row.week, value);
  }
  let total = 0;
  for (const value of byWeek.values()) total += value;
  return { total: Math.round(total * 100) / 100, weeks: byWeek.size };
}

/** `in 3 rostered weeks` — the caption under the season figure. */
export function rosteredWeeksCaption(weeks: number): string {
  return `in ${weeks} rostered ${weeks === 1 ? "week" : "weeks"}`;
}
