import type { RosterPlayer, RosterSlot } from "../types";

/**
 * Comparator results, named so the null handling below reads as intent rather than as sign
 * arithmetic. `Array.prototype.sort` only looks at the sign, so the magnitude is irrelevant.
 */
const A_BEFORE_B = -1;
const B_BEFORE_A = 1;
const TIED = 0;

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
 * Fixed-locale collator so the name tie-break is the same on the Mac mini, in CI, and in a
 * browser. Bare `localeCompare` follows the host locale, which would make the order depend on
 * the environment for names that differ only by accent or case.
 */
const PLAYER_NAME_COLLATOR = new Intl.Collator("en");

/**
 * A total order over one team's roster: slot rank first, then lineup order inside the lineup and
 * projection descending everywhere else, then name. Ties fall through to the name so the roster
 * does not depend on the order the rows arrived in.
 */
export function compareRosterPlayers(a: RosterPlayer, b: RosterPlayer): number {
  const slotDelta = SLOT_ORDER[a.slot] - SLOT_ORDER[b.slot];
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
    return PLAYER_NAME_COLLATOR.compare(a.fullName, b.fullName);
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
  return PLAYER_NAME_COLLATOR.compare(a.fullName, b.fullName);
}

/**
 * Sorts a copy; the caller's array is never touched, and the player objects are passed through by
 * reference. `compareRosterPlayers` is total, so ordering an already-ordered roster is a no-op.
 */
export function orderRoster(players: RosterPlayer[]): RosterPlayer[] {
  return [...players].sort(compareRosterPlayers);
}

export interface RosterGroup {
  slot: RosterSlot;
  label: string;
  players: RosterPlayer[];
}

/**
 * The roster cut into the sections the expanded card renders, empty sections omitted. This is the
 * single ordering entry point for a roster: it orders once and slices the groups out of that one
 * ordered array, so callers hand it the raw roster rather than pre-ordering it themselves.
 */
export function groupRosterBySlot(players: RosterPlayer[]): RosterGroup[] {
  const bySlot = new Map<RosterSlot, RosterPlayer[]>();
  for (const player of orderRoster(players)) {
    const inSlot = bySlot.get(player.slot);
    if (inSlot === undefined) {
      bySlot.set(player.slot, [player]);
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
