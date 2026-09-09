import type { RosterPlayer, RosterSlot } from "../types";
import { A_BEFORE_B, B_BEFORE_A, NAME_COLLATOR, TIED } from "./compare";

/**
 * The rank each slot sorts at: the lineup first, then the bench, then the two parked slots.
 * Injured reserve sits above the taxi squad because an IR player is on this season's roster and
 * a taxi player is the furthest thing from playable.
 */
export const SLOT_ORDER: Record<RosterSlot, number> = {
  starter: 0,
  bench: 1,
  ir: 2,
  taxi: 3,
};

export const SLOT_LABELS: Record<RosterSlot, string> = {
  starter: "Starters",
  bench: "Bench",
  ir: "Injured reserve",
  taxi: "Taxi squad",
};

/**
 * Derived from `SLOT_ORDER` rather than written out again, so a new slot cannot be ranked in one
 * place and forgotten in the other.
 */
const SLOTS_IN_RENDER_ORDER: RosterSlot[] = (
  Object.keys(SLOT_ORDER) as RosterSlot[]
).sort((a, b) => SLOT_ORDER[a] - SLOT_ORDER[b]);

/**
 * A starter Sleeper gave us no lineup index for still has to land somewhere; it sorts after
 * every placed starter rather than jumping to the front of the lineup.
 */
const UNPLACED_STARTER_INDEX = Number.MAX_SAFE_INTEGER;

/**
 * Where a slot this build has never heard of lands. A frozen `final_rosters.holdings` row is
 * jsonb written by an earlier build, and Sleeper can add a slot at any time, so `slot` is only
 * `RosterSlot` by declaration. An unranked slot would make the comparator return `NaN` and drop
 * the player out of every group, which loses a real player from the card — the bench is the
 * honest home for "on the roster, not in the lineup".
 */
const FALLBACK_SLOT: RosterSlot = "bench";

/** The slot's rank, or the bench's rank when the slot is not one this build knows. */
function slotRank(slot: RosterSlot): number {
  const rank: number | undefined = SLOT_ORDER[slot];
  return rank ?? SLOT_ORDER[FALLBACK_SLOT];
}

/** The group an unknown slot renders in, so no roster row is silently dropped. */
function groupSlotFor(slot: RosterSlot): RosterSlot {
  return SLOT_ORDER[slot] === undefined ? FALLBACK_SLOT : slot;
}

/**
 * A total order over one team's roster: slot rank first, then lineup order inside the lineup and
 * projection descending everywhere else, then name. Ties fall through to the name so the roster
 * does not depend on the order the rows arrived in.
 */
export function compareRosterPlayers(a: RosterPlayer, b: RosterPlayer): number {
  const slotDelta = slotRank(a.slot) - slotRank(b.slot);
  if (slotDelta !== TIED) {
    return slotDelta;
  }

  if (a.slot === "starter") {
    // Starters read in the league's own lineup order, not by score.
    const left = a.slotIndex ?? UNPLACED_STARTER_INDEX;
    const right = b.slotIndex ?? UNPLACED_STARTER_INDEX;
    if (left !== right) {
      return left - right;
    }
    return NAME_COLLATOR.compare(a.fullName, b.fullName);
  }

  // null means "no projection", never zero, so it sorts below every projected player.
  const left = a.projectedPoints;
  const right = b.projectedPoints;
  if (left !== null && right === null) {
    return A_BEFORE_B;
  }
  if (left === null && right !== null) {
    return B_BEFORE_A;
  }
  if (left !== null && right !== null && left !== right) {
    return right - left;
  }
  return NAME_COLLATOR.compare(a.fullName, b.fullName);
}

/**
 * Sorts a copy; the caller's array is never touched, and the player objects are passed through by
 * reference. `compareRosterPlayers` is total, so ordering an already-ordered roster is a no-op.
 */
export function orderRoster(players: RosterPlayer[]): RosterPlayer[] {
  return [...players].sort(compareRosterPlayers);
}

/**
 * What an appended starter is called when nothing names its position: no `lineup_position` from
 * Sleeper and no directory row to read a position off. The row still renders — losing a player
 * is worse than labelling one vaguely.
 */
export const UNPLACED_STARTER_LABEL = "Starter";

/**
 * One line of the lineup: a slot from `seasons.roster_positions`, filled or not. An empty row is
 * the whole point of the type — a lineup with a hole in it is information the board owes the
 * league, not an absence to render nothing for.
 */
export type StarterSlotRow =
  | { kind: "filled"; position: string; player: RosterPlayer }
  | { kind: "empty"; position: string };

/**
 * `seasons.roster_positions` is jsonb, so it is only `string[]` by declaration — the column is
 * written by the sync and read here by a build that cannot vouch for what is at rest. Anything
 * that is not an array of strings degrades to "no lineup known", which lays every starter out as
 * an appended row and claims no slot is empty, rather than inventing slots from junk.
 */
export function parseRosterPositions(raw: unknown): string[] {
  return Array.isArray(raw)
    ? raw.filter((entry): entry is string => typeof entry === "string")
    : [];
}

/**
 * The lineup as the league defines it: one row per entry in `roster_positions`, in that order,
 * filled from the starters whose `slotIndex` names the slot — Sleeper's own index into
 * `starters`, which is index-aligned with `roster_positions`.
 *
 * A slot no starter claims comes back `empty`, which is the feature: an unfilled FLEX is the
 * thing a reader most needs to see and the old panel hid it by rendering only the players that
 * existed. Starters this layout cannot place — an index past the last slot, no index at all, or
 * a second player claiming a slot already taken — are appended after the known slots rather than
 * dropped, so no player ever falls off a card. Frozen `final_rosters` snapshots arrive as the
 * same `RosterPlayer` rows and lay out through this same function.
 *
 * Pure: sorts a copy, and the player objects are passed through by reference.
 */
export function layoutStarters(
  rosterPositions: readonly string[],
  players: readonly RosterPlayer[],
): StarterSlotRow[] {
  const byIndex = new Map<number, RosterPlayer>();
  const appended: RosterPlayer[] = [];

  // Ordered first, so the layout does not depend on the order the rows arrived in: which of two
  // starters claiming one slot keeps it, and the order of the appended rows, are both decided by
  // the roster's own total order rather than by the query's.
  for (const player of orderRoster([...players])) {
    if (player.slot !== "starter") {
      continue;
    }
    const index = player.slotIndex;
    const placeable =
      index !== null &&
      Number.isInteger(index) &&
      index >= 0 &&
      index < rosterPositions.length &&
      !byIndex.has(index);
    if (placeable) {
      byIndex.set(index as number, player);
    } else {
      appended.push(player);
    }
  }

  const rows: StarterSlotRow[] = rosterPositions.map((position, index) => {
    const player = byIndex.get(index);
    return player === undefined
      ? { kind: "empty", position }
      : { kind: "filled", position, player };
  });

  for (const player of appended) {
    rows.push({
      kind: "filled",
      position:
        player.lineupPosition ?? player.position ?? UNPLACED_STARTER_LABEL,
      player,
    });
  }
  return rows;
}

/** How many lineup slots nobody is starting in. */
export function countEmptyStarterSlots(rows: StarterSlotRow[]): number {
  return rows.filter((row) => row.kind === "empty").length;
}

/**
 * The empty-slot count the card shows. `team_week_projections.empty_slots` leads when there is a
 * projection row: it was computed against the same roster the projection beside it was, so the
 * two numbers always describe one lineup. With no projection row for the week there is nothing
 * to disagree with, and the layout's own count is the answer.
 */
export function resolveEmptySlotCount(
  reported: number | null,
  rows: StarterSlotRow[],
): number {
  return reported ?? countEmptyStarterSlots(rows);
}

export interface RosterGroup {
  slot: RosterSlot;
  label: string;
  players: RosterPlayer[];
}

/**
 * The roster cut into the sections the expanded card renders, empty sections omitted. This is the
 * single ordering entry point for a roster: it orders once and slices the groups out of that one
 * ordered array, so callers hand it the raw roster rather than pre-ordering it themselves. Rows
 * carrying a slot this build does not rank land in the bench group rather than disappearing.
 */
export function groupRosterBySlot(players: RosterPlayer[]): RosterGroup[] {
  const bySlot = new Map<RosterSlot, RosterPlayer[]>();
  for (const player of orderRoster(players)) {
    const slot = groupSlotFor(player.slot);
    const inSlot = bySlot.get(slot);
    if (inSlot === undefined) {
      bySlot.set(slot, [player]);
    } else {
      inSlot.push(player);
    }
  }

  const groups: RosterGroup[] = [];
  for (const slot of SLOTS_IN_RENDER_ORDER) {
    const inSlot = bySlot.get(slot);
    if (inSlot !== undefined) {
      groups.push({ slot, label: SLOT_LABELS[slot], players: inSlot });
    }
  }
  return groups;
}
