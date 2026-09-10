import type { BoardTeam } from "../types";
import type { CurveBand, FaabCurve } from "./curve";

/**
 * A line for each $50 band on the FAAB curve (Ben, 2026-09-10: "the taglines in each little
 * highlighted section on the chart"). Keyed off how many deviations the band's middle sits from
 * the league's mean, so the words follow the money as it moves through the season, with a
 * mention when the band holds the richest or the poorest wallet in the league.
 */
export function bandTagline(
  band: CurveBand,
  curve: FaabCurve,
  teams: readonly BoardTeam[],
  richest: BoardTeam | null,
  poorest: BoardTeam | null,
): string {
  const mid = (band.from + band.to) / 2;
  const z = (mid - curve.mean) / (curve.sd || 1);
  let line: string;
  if (teams.length === 0) {
    line =
      z > 1
        ? "Nobody up here. The air is thin."
        : z < -1
          ? "Empty. Nobody has fallen this far."
          : "Nobody lives here right now.";
  } else if (z >= 1.5) {
    line = "The penthouse. FAAB is not a constraint, it is a personality.";
  } else if (z >= 1) {
    line = "Comfortably loaded. Can outbid anyone who blinks.";
  } else if (z >= 0.5) {
    line = "Above the fold. A real war chest, if they ever use it.";
  } else if (z > -0.5) {
    line = "The middle of the pack. Enough to matter, not enough to bully.";
  } else if (z > -1) {
    line = "Tightening the belt. One bad bid from the bargain bin.";
  } else if (z > -1.5) {
    line = "Ramen for dinner. Every dollar has a name on it.";
  } else {
    line = "The gulag's waiting room. Pray for waivers nobody wants.";
  }
  const notes: string[] = [];
  if (richest && teams.some((t) => t.teamId === richest.teamId)) {
    notes.push(`${richest.ownerName} has the fattest wallet in the league.`);
  }
  if (poorest && teams.some((t) => t.teamId === poorest.teamId)) {
    notes.push(`${poorest.ownerName} is the poorest team in the league.`);
  }
  return [line, ...notes].join(" ");
}
