import type { BoardTeam } from "../types";

/** Decimals a live score is shown with, matching every other number on the board. */
export const SCORE_DECIMALS = 1;

/**
 * What the card shows before anybody has scored, and when the week has no score row yet.
 *
 * Ben's ruling is explicit that this is not an em dash: a score of nothing is a real answer,
 * and the whole week starts there. The em dash stays reserved for the projection, where a
 * missing number genuinely is unknowable — see `PROJECTION_UNAVAILABLE_TEXT`.
 */
export const SCORE_ZERO_TEXT = "0.0";

/** The two captions under the figures, spelled once so the card and its tests cannot drift. */
export const SCORE_CAPTION = "Score";
export const PROJECTION_CAPTION = "Proj";

/**
 * The accessible names for the same two figures. `Score 84.2` read out on its own could be a
 * score of anything, and `Proj` is not a word; both are spelled out for a screen reader.
 */
export const SCORE_LABEL = "Current score";
export const PROJECTION_LABEL = "Projected points";

/** Which of the two figures is the large one. */
export type CardEmphasis = "score" | "projection";

/**
 * A live score as the card renders it. A null score is `0.0`, not an em dash — see
 * `SCORE_ZERO_TEXT`.
 */
export function formatScore(score: number | null): string {
  return score === null ? SCORE_ZERO_TEXT : score.toFixed(SCORE_DECIMALS);
}

/** True once any visible team has actually scored something this week. */
export function hasLiveScores(teams: readonly BoardTeam[]): boolean {
  return teams.some((team) => team.score !== null && team.score !== 0);
}

/**
 * Which figure the whole board emphasises, decided once for every card rather than per card.
 *
 * Ben asked for the score beside the projection, and before kickoff the score is eighteen
 * zeroes: making it the large figure then would put a wall of `0.0` where the number people
 * actually read on a Saturday is the projection. So the emphasis flips when the first point of
 * the week is scored, and it flips for the whole board at once — which is also what keeps the
 * two figure columns the same width down the grid, since every card sizes them the same way.
 */
export function resolveCardEmphasis(teams: readonly BoardTeam[]): CardEmphasis {
  return hasLiveScores(teams) ? "score" : "projection";
}

/**
 * The newest `synced_at` across the week's score rows, as an epoch, or null when no team has
 * one. This is what the header's `Scores updated` stamp reads: the sync writes it on every run,
 * unlike `team_week_projections.computed_at`, which only moves when a projection is recomputed
 * — the "why does it show that it updated at 9:30PM" half of Ben's complaint.
 */
export function newestScoreSyncedAt(
  teams: readonly BoardTeam[],
): number | null {
  let newest: number | null = null;
  for (const team of teams) {
    if (team.scoreSyncedAt === null) {
      continue;
    }
    const syncedAt = Date.parse(team.scoreSyncedAt);
    if (Number.isNaN(syncedAt)) {
      continue;
    }
    newest = newest === null ? syncedAt : Math.max(newest, syncedAt);
  }
  return newest;
}
