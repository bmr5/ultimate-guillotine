import type { BoardTeam } from "../types";
import { hasLiveScores } from "./score";

export interface CutWatchStanding {
  team: BoardTeam;
  points: number;
  gap: number | null;
}

export type CutWatchState =
  | { kind: "waiting"; message: string }
  | {
      kind: "ranked";
      basis: "score" | "projection";
      teams: CutWatchStanding[];
      tied: boolean;
      partial: boolean;
    };

/** The Daily's week-scoped event identifies the eligible pool after Week 1. */
export function cutWatch(
  teams: readonly BoardTeam[],
  week: number,
): CutWatchState {
  const active = teams.filter((team) => !team.isEliminated);
  if (
    week > 1 &&
    (active.some(
      (team) =>
        team.risk?.adverseEvent !== "gulag_entry" &&
        team.risk?.adverseEvent !== "gulag_loss",
    ) ||
      active.filter((team) => team.risk?.adverseEvent === "gulag_loss")
        .length !== 2)
  ) {
    return {
      kind: "waiting",
      message:
        "Waiting for this week's gulag pairing to confirm the eligible pool.",
    };
  }

  const pool = active.filter(
    (team) => week === 1 || team.risk?.adverseEvent === "gulag_entry",
  );
  const basis = hasLiveScores(active) ? "score" : "projection";
  const points = (team: BoardTeam) =>
    basis === "score" ? team.score : team.projectedPoints;

  // A missing team could be below the cutoff. Never silently rank a partial pool.
  if (
    pool.length < 3 ||
    pool.some((team) => points(team) === null || !Number.isFinite(points(team)))
  ) {
    return {
      kind: "waiting",
      message:
        basis === "score"
          ? "Waiting for scores for the full eligible pool."
          : "Waiting for projections for the full eligible pool.",
    };
  }

  const ranked = [...pool].sort(
    (a, b) =>
      (points(a) as number) - (points(b) as number) ||
      // Projections only choose which tied teams to preview, never settle the cut.
      (basis === "score"
        ? (a.projectedPoints ?? Infinity) - (b.projectedPoints ?? Infinity)
        : 0) ||
      a.sleeperRosterId - b.sleeperRosterId,
  );
  const cutoff = points(ranked[1]) as number;
  // Show everyone tied across the boundary instead of inventing a tiebreaker.
  const atRisk = ranked.filter((team) => (points(team) as number) <= cutoff);
  const safePoints = points(ranked[2]) as number;
  return {
    kind: "ranked",
    basis,
    teams: atRisk.map((team) => ({
      team,
      points: points(team) as number,
      gap: atRisk.length > 2 ? null : safePoints - (points(team) as number),
    })),
    tied: atRisk.length > 2,
    partial: basis === "projection" && pool.some((team) => team.isProvisional),
  };
}
