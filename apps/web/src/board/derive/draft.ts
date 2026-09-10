import type { DraftPickRow } from "../fetchers";
import type { DraftPickInfo } from "../types";

/** The season's picks keyed by player, in the shape a roster row carries. */
export function indexDraftPicks(
  rows: readonly DraftPickRow[],
): Map<string, DraftPickInfo> {
  const index = new Map<string, DraftPickInfo>();
  for (const row of rows) {
    index.set(row.sleeper_player_id, {
      teamId: row.team_id,
      amount: row.amount,
      pickNo: row.pick_no,
      round: row.round,
      position: row.position,
      draftedAt: row.drafted_at,
    });
  }
  return index;
}

/**
 * The one-line rule behind the mark: the pick belongs to the team whose row this is. A
 * player traded away and back is "still here" too — the journey tells that story.
 */
export function draftedHere(
  pick: DraftPickInfo | null,
  teamId: number,
): boolean {
  return pick !== null && pick.teamId === teamId;
}

/** `1st`, `2nd`, `3rd`, `4th`, … with the teens as `th`. */
export function ordinal(n: number): string {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
}

export interface AuctionContext {
  /** Competition rank by price over the whole auction: tied prices share the higher rank. */
  overallRank: number;
  pickCount: number;
  position: string | null;
  /** The same rank among picks at the same position; null when the pick has no position. */
  positionRank: number | null;
  positionCount: number;
  /** The mean price at the position, rounded to the dollar; null when there is no position. */
  positionAverage: number | null;
}

/** Where a pick's price sat in the auction, overall and at its position. */
export function auctionContext(
  pick: DraftPickInfo,
  picks: Iterable<DraftPickInfo>,
): AuctionContext {
  let pickCount = 0;
  let pricier = 0;
  let positionCount = 0;
  let positionPricier = 0;
  let positionTotal = 0;
  for (const other of picks) {
    pickCount += 1;
    if (other.amount > pick.amount) pricier += 1;
    if (pick.position !== null && other.position === pick.position) {
      positionCount += 1;
      positionTotal += other.amount;
      if (other.amount > pick.amount) positionPricier += 1;
    }
  }
  const hasPosition = pick.position !== null && positionCount > 0;
  return {
    overallRank: pricier + 1,
    pickCount,
    position: pick.position,
    positionRank: hasPosition ? positionPricier + 1 : null,
    positionCount,
    positionAverage: hasPosition
      ? Math.round(positionTotal / positionCount)
      : null,
  };
}

/** The mark's accessible name; the sentence behind it is `draftedHereDescription`. */
export const DRAFTED_HERE_LABEL = "Drafted here";

/** What the mark's tooltip says, spelled once so the row and its tests cannot drift. */
export function draftedHereDescription(
  ownerName: string,
  amount: number,
): string {
  return `Drafted by ${ownerName} for $${amount}`;
}

/** The card's context line: `9th priciest pick · 4th RB · RB average $22`. */
export function auctionContextLine(context: AuctionContext): string {
  const parts = [`${ordinal(context.overallRank)} priciest pick`];
  if (
    context.position !== null &&
    context.positionRank !== null &&
    context.positionAverage !== null
  ) {
    parts.push(`${ordinal(context.positionRank)} ${context.position}`);
    parts.push(`${context.position} average $${context.positionAverage}`);
  }
  return parts.join(" · ");
}
