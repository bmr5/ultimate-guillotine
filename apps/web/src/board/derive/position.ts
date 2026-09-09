import {
  DEFAULT_POSITION_SORT_MODE,
  type BoardTeam,
  type PositionFilter,
  type RosterPlayer,
  type SortMode,
} from "../types";
import { A_BEFORE_B, B_BEFORE_A, NAME_COLLATOR, TIED } from "./compare";
import { layoutStarters } from "./roster";
import { sortValue } from "./sort";

/**
 * The slots that accept more than the position they are named for. An empty FLEX is a hole a
 * running back, receiver or tight end could fill, so it counts as one in each of those views —
 * which is exactly the question Ben asked the view to answer ("my TE just got injured and I
 * need to figure out who would bid on his replacement"). Slots not named here accept only their
 * own position, which covers `QB`, `RB`, `WR`, `TE`, `K` and `DEF`.
 */
export const MULTI_POSITION_SLOTS: Record<string, readonly PositionFilter[]> = {
  FLEX: ["RB", "WR", "TE"],
  WRRB_FLEX: ["RB", "WR"],
  REC_FLEX: ["WR", "TE"],
  SUPER_FLEX: ["QB", "RB", "WR", "TE"],
};

/** Whether a player at `position` could start in a slot spelled `slot`. */
export function slotAcceptsPosition(
  slot: string,
  position: PositionFilter,
): boolean {
  const named = slot.trim().toUpperCase();
  const accepted = MULTI_POSITION_SLOTS[named];
  return accepted === undefined
    ? named === position
    : accepted.includes(position);
}

export interface PositionPlayer {
  sleeperPlayerId: string;
  fullName: string;
  /** null means "no projection", never zero. */
  projectedPoints: number | null;
  /** True for a player in the lineup, so the row can mark him. */
  isStarter: boolean;
}

export interface PositionRow {
  /** The whole team, so a row can expand into the board's usual roster panel. */
  team: BoardTeam;
  teamId: number;
  ownerName: string;
  teamName: string;
  faabRemaining: number | null;
  isEliminated: boolean;
  /** The team's players at this position: starters first, marked; everyone else after. */
  players: PositionPlayer[];
  /** Empty lineup slots a player at this position could fill; a FLEX counts for RB, WR and TE. */
  emptySlots: number;
  /** An empty slot at the position, or a best starter below the visible median. */
  likelyBidder: boolean;
}

/** The best projection among a team's starters at the position; null when there is none. */
function bestStarterProjection(players: PositionPlayer[]): number | null {
  let best: number | null = null;
  for (const player of players) {
    if (!player.isStarter || player.projectedPoints === null) {
      continue;
    }
    best =
      best === null
        ? player.projectedPoints
        : Math.max(best, player.projectedPoints);
  }
  return best;
}

/** The middle value, averaging the two middles for an even count; null for nothing to take. */
function median(values: number[]): number | null {
  if (values.length === 0) {
    return null;
  }
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

/** Descending, with null — "not comparable" — always last. Never coerced to zero. */
function compareDescending(left: number | null, right: number | null): number {
  if (left !== null && right === null) {
    return A_BEFORE_B;
  }
  if (left === null && right !== null) {
    return B_BEFORE_A;
  }
  if (left !== null && right !== null && left !== right) {
    return right - left;
  }
  return TIED;
}

/**
 * A total order over the rows: the chosen key descending, then the other one, then the owner
 * label, then the team id. Eliminated teams are partitioned out before this runs — they are
 * dimmed at the bottom rather than mixed in — so elimination is not part of the comparison.
 */
function comparePositionRows(
  a: PositionRow,
  b: PositionRow,
  mode: SortMode,
): number {
  const primary: SortMode = mode === "projection" ? "projection" : "faab";
  const secondary: SortMode = primary === "faab" ? "projection" : "faab";
  for (const key of [primary, secondary]) {
    const delta = compareDescending(
      sortValue(a.team, key),
      sortValue(b.team, key),
    );
    if (delta !== TIED) {
      return delta;
    }
  }
  const byOwner = NAME_COLLATOR.compare(a.ownerName, b.ownerName);
  if (byOwner !== TIED) {
    return byOwner;
  }
  return a.teamId - b.teamId;
}

function toPositionPlayer(player: RosterPlayer): PositionPlayer {
  return {
    sleeperPlayerId: player.sleeperPlayerId,
    fullName: player.fullName,
    projectedPoints: player.projectedPoints,
    isStarter: player.slot === "starter",
  };
}

/**
 * The whole league at one position, one row per team.
 *
 * Ben's addendum 2: "make it possible so I can filter and see every team's TE or all their RBs
 * in a quick view — my TE just got injured and I need to figure out who would bid on his
 * replacement." So every team gets a row whether or not it holds the position: a team with none
 * is the most interesting row on the page.
 *
 * `likelyBidder` is a hint, not a ruling: a team with an empty slot the position could fill, or
 * one whose best starter there projects below the median of what is on screen. The median comes
 * from the teams passed in — the search-filtered, visible set — so the flag answers "who bids in
 * what I am looking at" rather than a league-wide constant.
 *
 * Pure: sorts copies, and the team and player objects are passed through by reference.
 */
export function positionView(
  teams: BoardTeam[],
  position: PositionFilter,
  rosterPositions: readonly string[],
  mode: SortMode = DEFAULT_POSITION_SORT_MODE,
): PositionRow[] {
  const rows: PositionRow[] = teams.map((team) => {
    const atPosition = team.roster.filter(
      (player) => (player.position ?? "").trim().toUpperCase() === position,
    );
    // Starters lead and are marked; the bench follows in the roster's own order, which is
    // projection descending. `orderRoster` already ran in the join, so this only partitions.
    const players = [
      ...atPosition.filter((player) => player.slot === "starter"),
      ...atPosition.filter((player) => player.slot !== "starter"),
    ].map(toPositionPlayer);

    const emptySlots = layoutStarters(rosterPositions, team.roster).filter(
      (row) =>
        row.kind === "empty" && slotAcceptsPosition(row.position, position),
    ).length;

    return {
      team,
      teamId: team.teamId,
      ownerName: team.ownerName,
      teamName: team.teamName,
      faabRemaining: team.faabRemaining,
      isEliminated: team.isEliminated,
      players,
      emptySlots,
      likelyBidder: false,
    };
  });

  const leagueMedian = median(
    rows
      .map((row) => bestStarterProjection(row.players))
      .filter((best): best is number => best !== null),
  );

  for (const row of rows) {
    const best = bestStarterProjection(row.players);
    row.likelyBidder =
      row.emptySlots > 0 ||
      (best !== null && leagueMedian !== null && best < leagueMedian);
  }

  // Eliminated teams stay in the payload — they are dimmed and still expandable, and their
  // frozen rosters are part of the answer to "who holds this position" — they simply never mix
  // in with the living.
  const active = rows.filter((row) => !row.isEliminated);
  const eliminated = rows.filter((row) => row.isEliminated);
  return [
    ...active.sort((a, b) => comparePositionRows(a, b, mode)),
    ...eliminated.sort((a, b) => comparePositionRows(a, b, mode)),
  ];
}
