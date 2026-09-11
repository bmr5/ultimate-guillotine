import type { RosterPlayer } from "../types";
import { isUnavailable } from "./availability";

export type GameStatus = "remaining" | "live" | "done" | "bye";
export type WeekSchedule = Record<string, GameStatus>;

export function parseWeekSchedule(
  payload: unknown,
  week: number,
): WeekSchedule {
  if (!Array.isArray(payload)) throw new Error("NFL schedule unavailable");
  const schedule: WeekSchedule = {};
  for (const game of payload) {
    if (
      !game ||
      game.week !== week ||
      typeof game.home !== "string" ||
      typeof game.away !== "string" ||
      typeof game.status !== "string"
    )
      continue;
    const status = ["complete", "canceled"].includes(game.status)
      ? "done"
      : game.status === "pre_game"
        ? "remaining"
        : "live";
    schedule[game.home] = status;
    schedule[game.away] = status;
  }
  if (!Object.keys(schedule).length)
    throw new Error("NFL schedule unavailable");
  // Teams absent from a valid week have a bye. Unknown directory codes remain unavailable.
  for (const team of "ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LAC LAR LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS".split(
    " ",
  )) {
    schedule[team] ??= "bye";
  }
  return schedule;
}

/** Actual points plus the part of each unfinished starter's estimate not yet scored.
 * Finished zeroes and negative scores count. Live players retain their full-game
 * estimate until they exceed it; this is not a clock-based in-game model.
 */
export function currentProjection(
  roster: readonly Pick<
    RosterPlayer,
    | "sleeperPlayerId"
    | "slot"
    | "nflTeam"
    | "projectedPoints"
    | "livePoints"
    | "injuryStatus"
  >[],
  score: number | null,
  schedule: WeekSchedule | null | undefined,
  scoreStarters?: readonly string[],
): number | null {
  if (!schedule) return null;
  const starters = roster.filter((player) => player.slot === "starter");
  if (!starters.length) return null;
  if (scoreStarters) {
    const scoredIds = new Set(scoreStarters.filter((id) => id !== "0"));
    // Do not combine scores and projections from different lineup versions.
    if (
      scoredIds.size !== starters.length ||
      starters.some((p) => !scoredIds.has(p.sleeperPlayerId))
    )
      return null;
  }
  let total = score ?? 0;
  for (const player of starters) {
    const status = player.nflTeam ? schedule[player.nflTeam] : undefined;
    if (!status) return null;
    if (
      status === "bye" ||
      (status === "remaining" && isUnavailable(player.injuryStatus))
    )
      continue;
    if (
      status !== "remaining" &&
      (score === null || player.livePoints === null)
    )
      return null;
    if (status === "done") continue;
    if (
      player.projectedPoints === null ||
      !Number.isFinite(player.projectedPoints)
    )
      return null;
    const remaining = player.projectedPoints - (player.livePoints ?? 0);
    total += status === "live" ? Math.max(0, remaining) : remaining;
  }
  return Number.isFinite(total) ? Math.round(total * 100) / 100 : null;
}
