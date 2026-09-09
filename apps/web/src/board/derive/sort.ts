import type { BoardTeam, SortMode } from "../types";
import { A_BEFORE_B, B_BEFORE_A, NAME_COLLATOR, TIED } from "./compare";
import { resolveProjectionDisplay } from "./projection";

/**
 * A Sleeper-inferred elimination can land before the week is known (`eliminated_week` is
 * nullable), and an unknown week cannot claim to be the newest casualty — it sorts to the end
 * of the eliminated group, below every team whose week we do know.
 */
const UNKNOWN_ELIMINATION_WEEK = 0;

/** The sort mode used when a projection sort has nothing to sort by. */
export const SORT_FALLBACK_MODE: SortMode = "points_for";

/** null means "not comparable" and always sorts last — never coerced to zero. */
export function sortValue(team: BoardTeam, mode: SortMode): number | null {
  if (mode === "faab") {
    return team.faabRemaining;
  }
  if (mode === "points_for") {
    return team.pointsFor;
  }
  const display = resolveProjectionDisplay(team);
  return display.kind === "value" ? display.points : null;
}

/**
 * A total order, so the same board renders the same way every time: the mode's key descending,
 * then points for descending, then team name ascending, then team id ascending. Teams with no
 * comparable key sort after every team that has one and fall through to the same tie-breaks.
 * Only comparing a team with itself returns 0.
 */
export function compareTeams(
  a: BoardTeam,
  b: BoardTeam,
  mode: SortMode,
): number {
  const left = sortValue(a, mode);
  const right = sortValue(b, mode);

  if (left !== null && right === null) {
    return A_BEFORE_B;
  }
  if (left === null && right !== null) {
    return B_BEFORE_A;
  }
  if (left !== null && right !== null && left !== right) {
    return right - left;
  }
  if (a.pointsFor !== b.pointsFor) {
    return b.pointsFor - a.pointsFor;
  }
  const byName = NAME_COLLATOR.compare(a.teamName, b.teamName);
  if (byName !== TIED) {
    return byName;
  }
  return a.teamId - b.teamId;
}

/**
 * Splits the board into the two groups the list renders. Eliminated teams stay in the payload —
 * they are dimmed and still expandable — they simply never mix in with the living.
 */
export function partitionByElimination(teams: BoardTeam[]): {
  active: BoardTeam[];
  eliminated: BoardTeam[];
} {
  const active: BoardTeam[] = [];
  const eliminated: BoardTeam[] = [];
  for (const team of teams) {
    if (team.isEliminated) {
      eliminated.push(team);
    } else {
      active.push(team);
    }
  }
  return { active, eliminated };
}

/**
 * Sorts a copy; the caller's array is never touched, and the team objects are passed through by
 * reference. `Array.prototype.sort` is stable, and `compareTeams` is total, so the result does
 * not depend on the incoming order.
 */
export function sortBoardTeams(
  teams: BoardTeam[],
  mode: SortMode,
): { active: BoardTeam[]; eliminated: BoardTeam[] } {
  const { active, eliminated } = partitionByElimination(teams);
  return {
    active: [...active].sort((a, b) => compareTeams(a, b, mode)),
    // Most recently eliminated first, so the newest casualty reads at the top of the group.
    eliminated: [...eliminated].sort((a, b) => {
      const aWeek = a.eliminatedWeek ?? UNKNOWN_ELIMINATION_WEEK;
      const bWeek = b.eliminatedWeek ?? UNKNOWN_ELIMINATION_WEEK;
      if (aWeek !== bWeek) {
        return bWeek - aWeek;
      }
      return compareTeams(a, b, mode);
    }),
  };
}

/** With projections off entirely, projection sort is meaningless; say so and use points for. */
export function selectEffectiveSortMode(
  teams: BoardTeam[],
  requested: SortMode,
): { mode: SortMode; fellBack: boolean } {
  if (requested !== "projection") {
    return { mode: requested, fellBack: false };
  }
  const hasUsableProjection = teams.some(
    (team) => resolveProjectionDisplay(team).kind === "value",
  );
  return hasUsableProjection
    ? { mode: "projection", fellBack: false }
    : { mode: SORT_FALLBACK_MODE, fellBack: true };
}
