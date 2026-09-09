/**
 * Roster ordering is comparisons over plain numbers and strings, so it runs under node like the
 * other derive modules.
 *
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { RosterPlayer, RosterSlot } from "../types";
import {
  countEmptyStarterSlots,
  groupRosterBySlot,
  layoutStarters,
  orderRoster,
  parseRosterPositions,
  resolveEmptySlotCount,
  SLOT_LABELS,
  SLOT_ORDER,
  UNPLACED_STARTER_LABEL,
  type StarterSlotRow,
} from "./roster";

const player = (
  over: Partial<RosterPlayer> & { sleeperPlayerId: string },
): RosterPlayer => ({
  fullName: `Player ${over.sleeperPlayerId}`,
  position: "WR",
  nflTeam: "SF",
  slot: "bench",
  slotIndex: null,
  lineupPosition: null,
  projectedPoints: null,
  injuryStatus: null,
  ...over,
});

describe("SLOT_ORDER and SLOT_LABELS", () => {
  it("covers every slot with a distinct rank and a label", () => {
    expect(Object.keys(SLOT_ORDER)).toEqual(["starter", "bench", "ir", "taxi"]);
    expect(new Set(Object.values(SLOT_ORDER)).size).toBe(4);
    expect(Object.keys(SLOT_LABELS)).toEqual(Object.keys(SLOT_ORDER));
  });
});

describe("orderRoster", () => {
  it("puts starters first in lineup slot order", () => {
    const ordered = orderRoster([
      player({ sleeperPlayerId: "c", slot: "bench", projectedPoints: 20 }),
      player({
        sleeperPlayerId: "b",
        slot: "starter",
        slotIndex: 1,
        lineupPosition: "RB",
      }),
      player({
        sleeperPlayerId: "a",
        slot: "starter",
        slotIndex: 0,
        lineupPosition: "QB",
      }),
    ]);
    expect(ordered.map((p) => p.sleeperPlayerId)).toEqual(["a", "b", "c"]);
  });

  it("orders bench, ir, then taxi after the starters", () => {
    const ordered = orderRoster([
      player({ sleeperPlayerId: "taxi", slot: "taxi" }),
      player({ sleeperPlayerId: "ir", slot: "ir" }),
      player({ sleeperPlayerId: "bench", slot: "bench" }),
      player({ sleeperPlayerId: "start", slot: "starter", slotIndex: 0 }),
    ]);
    expect(ordered.map((p) => p.sleeperPlayerId)).toEqual([
      "start",
      "bench",
      "ir",
      "taxi",
    ]);
  });

  it("orders non-starters by projection descending with missing projections last", () => {
    const ordered = orderRoster([
      player({ sleeperPlayerId: "none", slot: "bench", projectedPoints: null }),
      player({ sleeperPlayerId: "low", slot: "bench", projectedPoints: 3.2 }),
      player({ sleeperPlayerId: "high", slot: "bench", projectedPoints: 14.8 }),
    ]);
    expect(ordered.map((p) => p.sleeperPlayerId)).toEqual([
      "high",
      "low",
      "none",
    ]);
  });

  it("sorts a starter with no lineup index after every placed starter", () => {
    const ordered = orderRoster([
      player({ sleeperPlayerId: "unplaced", slot: "starter", slotIndex: null }),
      player({ sleeperPlayerId: "placed", slot: "starter", slotIndex: 3 }),
    ]);
    expect(ordered.map((p) => p.sleeperPlayerId)).toEqual([
      "placed",
      "unplaced",
    ]);
  });

  it("breaks ties by name so the order never depends on the incoming order", () => {
    const forwards = orderRoster([
      player({
        sleeperPlayerId: "z",
        slot: "starter",
        slotIndex: 0,
        fullName: "Zeke",
      }),
      player({
        sleeperPlayerId: "a",
        slot: "starter",
        slotIndex: 0,
        fullName: "Aaron",
      }),
    ]);
    const backwards = orderRoster([
      player({
        sleeperPlayerId: "a",
        slot: "starter",
        slotIndex: 0,
        fullName: "Aaron",
      }),
      player({
        sleeperPlayerId: "z",
        slot: "starter",
        slotIndex: 0,
        fullName: "Zeke",
      }),
    ]);
    expect(forwards.map((p) => p.sleeperPlayerId)).toEqual(["a", "z"]);
    expect(backwards.map((p) => p.sleeperPlayerId)).toEqual(["a", "z"]);
  });

  it("breaks equal bench projections by name", () => {
    const ordered = orderRoster([
      player({
        sleeperPlayerId: "z",
        slot: "bench",
        projectedPoints: 9,
        fullName: "Zeke",
      }),
      player({
        sleeperPlayerId: "a",
        slot: "bench",
        projectedPoints: 9,
        fullName: "Aaron",
      }),
    ]);
    expect(ordered.map((p) => p.sleeperPlayerId)).toEqual(["a", "z"]);
  });

  it("breaks two missing projections by name rather than by input order", () => {
    const ordered = orderRoster([
      player({
        sleeperPlayerId: "z",
        slot: "bench",
        projectedPoints: null,
        fullName: "Zeke",
      }),
      player({
        sleeperPlayerId: "a",
        slot: "bench",
        projectedPoints: null,
        fullName: "Aaron",
      }),
    ]);
    expect(ordered.map((p) => p.sleeperPlayerId)).toEqual(["a", "z"]);
  });

  it("does not mutate the input", () => {
    const players = [
      player({ sleeperPlayerId: "b", slot: "bench" }),
      player({ sleeperPlayerId: "a", slot: "starter", slotIndex: 0 }),
    ];
    orderRoster(players);
    expect(players.map((p) => p.sleeperPlayerId)).toEqual(["b", "a"]);
  });

  it("is idempotent, so re-ordering an ordered roster changes nothing", () => {
    const players = [
      player({ sleeperPlayerId: "taxi", slot: "taxi" }),
      player({ sleeperPlayerId: "b", slot: "starter", slotIndex: 1 }),
      player({ sleeperPlayerId: "high", slot: "bench", projectedPoints: 14.8 }),
      player({ sleeperPlayerId: "a", slot: "starter", slotIndex: 0 }),
    ];
    const once = orderRoster(players);
    expect(orderRoster(once).map((p) => p.sleeperPlayerId)).toEqual(
      once.map((p) => p.sleeperPlayerId),
    );
  });
});

describe("groupRosterBySlot", () => {
  it("labels each occupied slot group and skips empty ones", () => {
    const groups = groupRosterBySlot([
      player({ sleeperPlayerId: "a", slot: "starter", slotIndex: 0 }),
      player({ sleeperPlayerId: "b", slot: "bench" }),
    ]);
    expect(groups.map((g) => g.slot)).toEqual(["starter", "bench"]);
    expect(groups.map((g) => g.label)).toEqual(["Starters", "Bench"]);
    expect(groups[0].players.map((p) => p.sleeperPlayerId)).toEqual(["a"]);
  });

  it("labels the injured reserve and taxi groups", () => {
    const groups = groupRosterBySlot([
      player({ sleeperPlayerId: "t", slot: "taxi" }),
      player({ sleeperPlayerId: "i", slot: "ir" }),
    ]);
    expect(groups.map((g) => g.slot)).toEqual(["ir", "taxi"]);
    expect(groups.map((g) => g.label)).toEqual([
      "Injured reserve",
      "Taxi squad",
    ]);
  });

  it("orders players within a group and keeps every player exactly once", () => {
    const groups = groupRosterBySlot([
      player({ sleeperPlayerId: "low", slot: "bench", projectedPoints: 1 }),
      player({ sleeperPlayerId: "b", slot: "starter", slotIndex: 1 }),
      player({ sleeperPlayerId: "high", slot: "bench", projectedPoints: 30 }),
      player({ sleeperPlayerId: "a", slot: "starter", slotIndex: 0 }),
    ]);
    expect(
      groups.flatMap((g) => g.players.map((p) => p.sleeperPlayerId)),
    ).toEqual(["a", "b", "high", "low"]);
  });

  it("returns nothing for an empty roster", () => {
    expect(groupRosterBySlot([])).toEqual([]);
  });
});

describe("slots this build does not know", () => {
  /**
   * `slot` is `RosterSlot` by declaration only: a frozen roster is jsonb written by an earlier
   * build, and Sleeper can add a slot at any time. The cast is the point of the test — it stands
   * in for the value that actually arrives at runtime.
   */
  const unknownSlots: { label: string; slot: RosterSlot }[] = [
    { label: "a slot Sleeper added later", slot: "ir_taxi" as RosterSlot },
    { label: "an empty slot string", slot: "" as RosterSlot },
    { label: "a slot spelled differently", slot: "BENCH" as RosterSlot },
  ];

  it.each(unknownSlots)(
    "keeps a player carrying $label instead of dropping them",
    ({ slot }) => {
      const ordered = orderRoster([
        player({ sleeperPlayerId: "unknown", slot, projectedPoints: 5 }),
        player({ sleeperPlayerId: "start", slot: "starter", slotIndex: 0 }),
        player({ sleeperPlayerId: "taxi", slot: "taxi" }),
      ]);
      expect(ordered.map((p) => p.sleeperPlayerId)).toEqual([
        "start",
        "unknown",
        "taxi",
      ]);
    },
  );

  it.each(unknownSlots)(
    "folds a player carrying $label into the bench group",
    ({ slot }) => {
      const groups = groupRosterBySlot([
        player({ sleeperPlayerId: "unknown", slot, projectedPoints: 5 }),
        player({ sleeperPlayerId: "bench", slot: "bench", projectedPoints: 9 }),
      ]);
      expect(groups.map((g) => g.slot)).toEqual(["bench"]);
      expect(groups.map((g) => g.label)).toEqual(["Bench"]);
      expect(groups[0].players.map((p) => p.sleeperPlayerId)).toEqual([
        "bench",
        "unknown",
      ]);
    },
  );
});

/** The league's own lineup today, and the shape every layout case below is written against. */
const LEAGUE_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"];

const starter = (
  sleeperPlayerId: string,
  slotIndex: number | null,
  lineupPosition: string,
): RosterPlayer =>
  player({
    sleeperPlayerId,
    slot: "starter",
    slotIndex,
    lineupPosition,
    position: lineupPosition,
  });

/** Every lineup slot as `POSITION:id`, or `POSITION:empty` — the whole row list in one line. */
const summarize = (rows: StarterSlotRow[]): string[] =>
  rows.map((row) =>
    row.kind === "empty"
      ? `${row.position}:empty`
      : `${row.position}:${row.player.sleeperPlayerId}`,
  );

/** A full lineup, one player per slot in `LEAGUE_SLOTS` order. */
const FULL_LINEUP: RosterPlayer[] = LEAGUE_SLOTS.map((position, index) =>
  starter(`s${index}`, index, position),
);

/** The same lineup with the players at `missing` left out. */
const lineupWithout = (...missing: number[]): RosterPlayer[] =>
  FULL_LINEUP.filter((_, index) => !missing.includes(index));

interface LayoutCase {
  name: string;
  rosterPositions: string[];
  players: RosterPlayer[];
  expected: string[];
  emptyCount: number;
}

const LAYOUT_CASES: LayoutCase[] = [
  {
    name: "a full lineup: one row per slot, nothing empty",
    rosterPositions: LEAGUE_SLOTS,
    players: FULL_LINEUP,
    expected: [
      "QB:s0",
      "RB:s1",
      "RB:s2",
      "WR:s3",
      "WR:s4",
      "TE:s5",
      "FLEX:s6",
      "K:s7",
      "DEF:s8",
    ],
    emptyCount: 0,
  },
  {
    // Ben's case: Nick R is missing a flex, and the board has to say so.
    name: "one empty FLEX: the slot still gets its row",
    rosterPositions: LEAGUE_SLOTS,
    players: lineupWithout(6),
    expected: [
      "QB:s0",
      "RB:s1",
      "RB:s2",
      "WR:s3",
      "WR:s4",
      "TE:s5",
      "FLEX:empty",
      "K:s7",
      "DEF:s8",
    ],
    emptyCount: 1,
  },
  {
    name: "two empty slots: both rows, in lineup order",
    rosterPositions: LEAGUE_SLOTS,
    players: lineupWithout(5, 8),
    expected: [
      "QB:s0",
      "RB:s1",
      "RB:s2",
      "WR:s3",
      "WR:s4",
      "TE:empty",
      "FLEX:s6",
      "K:s7",
      "DEF:empty",
    ],
    emptyCount: 2,
  },
  {
    name: "an index past the last slot: appended, never dropped",
    rosterPositions: ["QB", "RB"],
    players: [starter("qb", 0, "QB"), starter("stray", 12, "WR")],
    expected: ["QB:qb", "RB:empty", "WR:stray"],
    emptyCount: 1,
  },
  {
    name: "a starter with no index at all: appended after the known slots",
    rosterPositions: ["QB", "RB"],
    players: [starter("rb", 1, "RB"), starter("unplaced", null, "WR")],
    expected: ["QB:empty", "RB:rb", "WR:unplaced"],
    emptyCount: 1,
  },
  {
    name: "two starters claiming one index: the second is appended, not lost",
    rosterPositions: ["QB"],
    players: [starter("first", 0, "QB"), starter("second", 0, "QB")],
    expected: ["QB:first", "QB:second"],
    emptyCount: 0,
  },
  {
    // A frozen `final_rosters` snapshot is built into the same `RosterPlayer` rows, so the
    // frozen lineup lays out through the same function and reads the same way.
    name: "a frozen roster: the same layout, empties and all",
    rosterPositions: LEAGUE_SLOTS,
    players: [
      starter("frozen-qb", 0, "QB"),
      starter("frozen-te", 5, "TE"),
      player({ sleeperPlayerId: "frozen-bench", slot: "bench" }),
    ],
    expected: [
      "QB:frozen-qb",
      "RB:empty",
      "RB:empty",
      "WR:empty",
      "WR:empty",
      "TE:frozen-te",
      "FLEX:empty",
      "K:empty",
      "DEF:empty",
    ],
    emptyCount: 7,
  },
  {
    name: "no roster positions known: every starter still gets a row, none empty",
    rosterPositions: [],
    players: [starter("qb", 0, "QB"), starter("rb", 1, "RB")],
    expected: ["QB:qb", "RB:rb"],
    emptyCount: 0,
  },
  {
    name: "bench, ir and taxi rows never enter the lineup",
    rosterPositions: ["QB"],
    players: [
      starter("qb", 0, "QB"),
      player({ sleeperPlayerId: "bench", slot: "bench" }),
      player({ sleeperPlayerId: "ir", slot: "ir" }),
      player({ sleeperPlayerId: "taxi", slot: "taxi" }),
    ],
    expected: ["QB:qb"],
    emptyCount: 0,
  },
];

describe("layoutStarters", () => {
  it.each(LAYOUT_CASES)("$name", ({ rosterPositions, players, expected }) => {
    expect(summarize(layoutStarters(rosterPositions, players))).toEqual(
      expected,
    );
  });

  it.each(LAYOUT_CASES)(
    "counts the empty slots for $name",
    ({ rosterPositions, players, emptyCount }) => {
      expect(
        countEmptyStarterSlots(layoutStarters(rosterPositions, players)),
      ).toBe(emptyCount);
    },
  );

  it("does not depend on the order the roster rows arrived in", () => {
    const shuffled = [...FULL_LINEUP].reverse();
    expect(summarize(layoutStarters(LEAGUE_SLOTS, shuffled))).toEqual(
      summarize(layoutStarters(LEAGUE_SLOTS, FULL_LINEUP)),
    );
  });

  it("does not mutate the roster it was handed", () => {
    const players = [...FULL_LINEUP].reverse();
    const ids = players.map((p) => p.sleeperPlayerId);
    layoutStarters(LEAGUE_SLOTS, players);
    expect(players.map((p) => p.sleeperPlayerId)).toEqual(ids);
  });

  it("names an appended starter by its position when it has no lineup position", () => {
    const rows = layoutStarters(
      ["QB"],
      [
        starter("qb", 0, "QB"),
        player({
          sleeperPlayerId: "stray",
          slot: "starter",
          slotIndex: null,
          lineupPosition: null,
          position: "WR",
        }),
      ],
    );
    expect(summarize(rows)).toEqual(["QB:qb", "WR:stray"]);
  });

  it("names an appended starter with nothing to go on as a plain starter", () => {
    const rows = layoutStarters(
      ["QB"],
      [
        player({
          sleeperPlayerId: "stray",
          slot: "starter",
          slotIndex: null,
          lineupPosition: null,
          position: null,
        }),
      ],
    );
    expect(summarize(rows)).toEqual([
      "QB:empty",
      `${UNPLACED_STARTER_LABEL}:stray`,
    ]);
  });
});

describe("resolveEmptySlotCount", () => {
  it("prefers the data layer's own count when there is one", () => {
    // `team_week_projections.empty_slots` is computed against the same roster the projection
    // was computed from, so it is the number the projection beside it actually reflects.
    const rows = layoutStarters(LEAGUE_SLOTS, lineupWithout(6));
    expect(resolveEmptySlotCount(3, rows)).toBe(3);
    expect(resolveEmptySlotCount(0, rows)).toBe(0);
  });

  it("falls back to the derived count when no projection row exists", () => {
    const rows = layoutStarters(LEAGUE_SLOTS, lineupWithout(6));
    expect(resolveEmptySlotCount(null, rows)).toBe(1);
  });
});

describe("parseRosterPositions", () => {
  it("passes a plain jsonb array of slot names through", () => {
    expect(parseRosterPositions(LEAGUE_SLOTS)).toEqual(LEAGUE_SLOTS);
  });

  it("keeps only the strings, so a malformed entry cannot become a slot", () => {
    expect(parseRosterPositions(["QB", 3, null, "RB", { slot: "WR" }])).toEqual(
      ["QB", "RB"],
    );
  });

  it("reads anything that is not an array as no lineup at all", () => {
    expect(parseRosterPositions(null)).toEqual([]);
    expect(parseRosterPositions(undefined)).toEqual([]);
    expect(parseRosterPositions("QB,RB")).toEqual([]);
    expect(parseRosterPositions({ 0: "QB" })).toEqual([]);
  });
});
