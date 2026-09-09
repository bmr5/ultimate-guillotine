/**
 * Roster ordering is comparisons over plain numbers and strings, so it runs under node like the
 * other derive modules.
 *
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { RosterPlayer, RosterSlot } from "../types";
import {
  groupRosterBySlot,
  orderRoster,
  SLOT_LABELS,
  SLOT_ORDER,
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
