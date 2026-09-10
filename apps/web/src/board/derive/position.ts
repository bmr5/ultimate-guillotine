import {
  DEFAULT_POSITION_SORT_MODE,
  type BoardTeam,
  type DraftPickInfo,
  type PositionFilter,
  type RosterPlayer,
  type SortMode,
} from "../types";
import { isOut } from "./availability";
import { A_BEFORE_B, B_BEFORE_A, NAME_COLLATOR, TIED } from "./compare";
import { PROJECTION_DECIMALS } from "./projection";
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
  /**
   * What he has actually scored this week, or null when the week has no score row. Unlike
   * `projectedPoints`, zero here is ordinary — it is what every player reads before kickoff.
   */
  livePoints: number | null;
  /** True for a player in the lineup, so the row can mark him. */
  isStarter: boolean;
  /**
   * The lineup slot a starter fills as Sleeper spells it (`WR`, `FLEX`, `SUPER_FLEX`), or
   * `BN` / `IR` / `TAXI` off the lineup. Ben (2026-09-10): the quick view breaks a team's
   * players down by the slot they start in, so four WRs read `WR WR FLEX BN`.
   */
  slotLabel: string;
  /** `players.injury_status`, so the row can tag him and the flag below can read him. */
  injuryStatus: string | null;
  /** The pick and the rule, exactly as the roster row carries them. */
  draft: DraftPickInfo | null;
  draftedHere: boolean;
}

/**
 * Why the board thinks a team is in the market, in the order the reasons are checked.
 *
 * `starter out` leads because it is a fact about this week rather than a comparison: a team
 * whose tight end is not playing needs one however well he projects on paper. `empty slot` is
 * next for the same reason. `below median` is the soft one, and it is relative to the visible
 * teams, so it is the last thing tried.
 */
export type LikelyBidderReason = "starter out" | "empty slot" | "below median";

/**
 * Each reason in words, for the `title` the `likely bidder` badge carries.
 *
 * The reason is the half of the answer a reader acts on: a team whose starter is out will bid
 * this week whatever his season looks like, and a team that is merely thin might not.
 */
export const LIKELY_BIDDER_REASONS: Record<LikelyBidderReason, string> = {
  "starter out": "Their starter at this position is out",
  "empty slot": "They have an empty slot this position could fill",
  "below median": "Their best starter here projects below the visible median",
};

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
  /** An out starter, an empty slot at the position, or a best starter below the median. */
  likelyBidder: boolean;
  /** Which of those it was; null when the team is not flagged. */
  likelyBidderReason: LikelyBidderReason | null;
  /**
   * The best projection among the team's starters at the position — the figure `below median`
   * compares — or null when no starter there has one.
   */
  bestStarterProjection: number | null;
  /**
   * The median of that figure across every team in the view, the same value on every row: it
   * rides on each so the badge can quote it without a second return value. Null when no
   * visible team has a projected starter at the position.
   */
  visibleMedian: number | null;
}

/**
 * The figures behind a `below median` flag, for the quieter second line of the badge's
 * tooltip: `Best starter 4.0 · median 12.0`.
 *
 * Ben (2026-09-10): the sentence said "below the visible median" without ever saying what the
 * median was. Null for the other two reasons, which compare nothing — and, defensively, for a
 * `below median` row missing either figure, which `positionView` never produces.
 */
export function likelyBidderFigures(row: PositionRow): string | null {
  if (
    row.likelyBidderReason !== "below median" ||
    row.bestStarterProjection === null ||
    row.visibleMedian === null
  ) {
    return null;
  }
  const bestText = row.bestStarterProjection.toFixed(PROJECTION_DECIMALS);
  const medianText = row.visibleMedian.toFixed(PROJECTION_DECIMALS);
  return `Best starter ${bestText} · median ${medianText}`;
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

const OFF_LINEUP_LABELS: Record<string, string> = {
  bench: "BN",
  ir: "IR",
  taxi: "TAXI",
};

/** The slot chip a player carries in the quick view. */
export function slotLabelFor(player: RosterPlayer): string {
  if (player.slot === "starter") {
    return (
      (player.lineupPosition ?? player.position ?? "").trim().toUpperCase() ||
      "STARTER"
    );
  }
  return OFF_LINEUP_LABELS[player.slot] ?? player.slot.toUpperCase();
}

/** What the slot chip's tooltip says. */
export function slotDescription(label: string, isStarter: boolean): string {
  if (!isStarter) {
    return label === "BN"
      ? "On the bench this week"
      : label === "IR"
        ? "On injured reserve, off the lineup"
        : "On the taxi squad, off the lineup";
  }
  return label in MULTI_POSITION_SLOTS
    ? `Starting in the ${label.replace("_", " ")} slot`
    : `Starting at ${label}`;
}

/**
 * Starters first in the order the lineup lists the slots -- the position's own slots, then
 * the flex kinds -- then the bench, then IR and taxi.
 */
function slotRankFor(player: RosterPlayer, position: PositionFilter): number {
  if (player.slot !== "starter") {
    return { bench: 10, ir: 11, taxi: 12 }[player.slot] ?? 13;
  }
  const label = slotLabelFor(player);
  if (label === position) return 0;
  return label in MULTI_POSITION_SLOTS ? 1 : 2;
}

function toPositionPlayer(player: RosterPlayer): PositionPlayer {
  return {
    sleeperPlayerId: player.sleeperPlayerId,
    fullName: player.fullName,
    projectedPoints: player.projectedPoints,
    livePoints: player.livePoints,
    isStarter: player.slot === "starter",
    slotLabel: slotLabelFor(player),
    injuryStatus: player.injuryStatus,
    draft: player.draft,
    draftedHere: player.draftedHere,
  };
}

/**
 * Whether the team is starting somebody at this position who is not playing this week.
 *
 * The same `isOut` rule the card's out chip uses, so the two readings of one lineup cannot
 * disagree: a `Doubtful` starter Sleeper has stopped projecting is a hole here as well.
 */
function hasOutStarter(players: PositionPlayer[]): boolean {
  return players.some(
    (player) =>
      player.isStarter && isOut(player.injuryStatus, player.projectedPoints),
  );
}

/**
 * The whole league at one position, one row per team.
 *
 * Ben's addendum 2: "make it possible so I can filter and see every team's TE or all their RBs
 * in a quick view — my TE just got injured and I need to figure out who would bid on his
 * replacement." So every team gets a row whether or not it holds the position: a team with none
 * is the most interesting row on the page.
 *
 * `likelyBidder` is a hint, not a ruling: a team starting somebody at the position who is not
 * playing this week, a team with an empty slot the position could fill, or one whose best
 * starter there projects below the median of what is on screen. The median comes from the teams
 * passed in — the search-filtered, visible set — so the flag answers "who bids in what I am
 * looking at" rather than a league-wide constant. `likelyBidderReason` says which rule fired,
 * because "why" is the half of the answer a reader acts on.
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
    // Starters lead, in slot order (`WR WR FLEX`), then the bench; within a rank the roster's
    // own order stands, which is projection descending (`orderRoster` already ran in the join).
    const players = atPosition
      .map((player, index) => ({ player, index }))
      .sort(
        (a, b) =>
          slotRankFor(a.player, position) - slotRankFor(b.player, position) ||
          a.index - b.index,
      )
      .map(({ player }) => toPositionPlayer(player));

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
      likelyBidderReason: null,
      bestStarterProjection: bestStarterProjection(players),
      visibleMedian: null,
    };
  });

  const leagueMedian = median(
    rows
      .map((row) => row.bestStarterProjection)
      .filter((best): best is number => best !== null),
  );

  for (const row of rows) {
    const best = row.bestStarterProjection;
    row.visibleMedian = leagueMedian;
    // Reasons in the order they are declared: a fact about this week beats a hole in the
    // lineup, and both beat a comparison against whoever else is on screen.
    row.likelyBidderReason = hasOutStarter(row.players)
      ? "starter out"
      : row.emptySlots > 0
        ? "empty slot"
        : best !== null && leagueMedian !== null && best < leagueMedian
          ? "below median"
          : null;
    row.likelyBidder = row.likelyBidderReason !== null;
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
