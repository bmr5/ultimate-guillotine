/**
 * Availability is arithmetic and string matching over plain values, so it runs under node
 * like the other derive modules.
 *
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { RosterPlayer } from "../types";
import {
  injuryTag,
  isOut,
  isUnavailable,
  KNOWN_INJURY_STATUSES,
  normalizeInjuryStatus,
  outReason,
  outStarters,
  resolveStarterAvailability,
  TENTATIVE_STATUSES,
  UNAVAILABLE_STATUSES,
  type StarterAvailabilityInput,
} from "./availability";
import { COVERAGE_GATE_PCT } from "./projection";
import type { StarterSlotRow } from "./roster";

const player = (
  over: Partial<RosterPlayer> & { sleeperPlayerId: string },
): RosterPlayer => ({
  fullName: "Starter",
  position: "TE",
  nflTeam: "KC",
  slot: "starter",
  slotIndex: 0,
  lineupPosition: "TE",
  projectedPoints: 9.4,
  injuryStatus: null,
  ...over,
});

const filled = (
  position: string,
  over: Partial<RosterPlayer> & { sleeperPlayerId: string },
): StarterSlotRow => ({ kind: "filled", position, player: player(over) });

const empty = (position: string): StarterSlotRow => ({
  kind: "empty",
  position,
});

/** A ten-slot lineup with every starter projected and fit. */
const healthyLineup = (): StarterSlotRow[] =>
  Array.from({ length: 10 }, (_, index) =>
    filled(`S${index}`, {
      sleeperPlayerId: `s${index}`,
      fullName: `Starter ${index}`,
      slotIndex: index,
    }),
  );

/** The lineup with one row replaced. */
const withRow = (rows: StarterSlotRow[], index: number, row: StarterSlotRow) =>
  rows.map((existing, at) => (at === index ? row : existing));

describe("injury status vocabulary", () => {
  it("names the statuses that mean a player is not playing", () => {
    // The six Sleeper values that take a player off the field whatever else is true of the
    // row. A doubt is not one of them on its own — see `outReason` for the case where a
    // withdrawn projection turns one into an absence anyway.
    expect([...UNAVAILABLE_STATUSES]).toEqual([
      "Out",
      "IR",
      "PUP",
      "Sus",
      "COV",
      "DNR",
    ]);
    expect([...TENTATIVE_STATUSES]).toEqual(["Questionable", "Doubtful"]);
  });

  it("knows the same nine statuses the sync stores", () => {
    // `KNOWN_INJURY_STATUSES` in `players.py`, in this build's own order.
    expect([...KNOWN_INJURY_STATUSES]).toEqual([
      "Out",
      "IR",
      "PUP",
      "Sus",
      "COV",
      "DNR",
      "Questionable",
      "Doubtful",
      "NA",
    ]);
  });

  it.each([
    ["Out", true],
    ["IR", true],
    ["PUP", true],
    ["Sus", true],
    ["COV", true],
    ["DNR", true],
    ["Questionable", false],
    ["Doubtful", false],
    // `NA` is Sleeper's "not active" bookkeeping flag, not a ruling on this week.
    ["NA", false],
    [null, false],
    ["", false],
  ])("reads %s as unavailable: %s", (status, expected) => {
    expect(isUnavailable(status)).toBe(expected);
  });

  it("trims and empties a status the way the sync does", () => {
    expect(normalizeInjuryStatus("  Out  ")).toBe("Out");
    expect(normalizeInjuryStatus("   ")).toBeNull();
    expect(normalizeInjuryStatus(undefined)).toBeNull();
  });

  it("gives every status a short tag and a full title", () => {
    expect(injuryTag("Out")).toEqual({
      status: "Out",
      tag: "Out",
      title: "Out",
      isUnavailable: true,
    });
    expect(injuryTag("IR")).toMatchObject({ tag: "IR", isUnavailable: true });
    expect(injuryTag("Questionable")).toMatchObject({
      tag: "Q",
      title: "Questionable",
      isUnavailable: false,
    });
    expect(injuryTag("Doubtful")).toMatchObject({
      tag: "D",
      title: "Doubtful",
    });
    expect(injuryTag(null)).toBeNull();
  });

  it("tags an unknown status by its own spelling rather than dropping it", () => {
    // The sync maps a status outside Sleeper's known vocabulary to null rather than storing
    // it, so this cannot come from a current row — but a stale bundle reading a row a newer
    // build wrote should still say something rather than nothing.
    expect(injuryTag("Sprained")).toMatchObject({
      tag: "Sprained",
      title: "Sprained",
      isUnavailable: false,
    });
  });
});

describe("outReason", () => {
  it.each([
    // A status that means absent is absent whether or not Sleeper still has a number.
    ["Out", null, "unavailable"],
    ["Out", 4.2, "unavailable"],
    ["IR", 9.4, "unavailable"],
    // Ben's tight end, 2026-09-09: flagged `Doubtful`, projection withdrawn.
    ["Doubtful", null, "no-projection"],
    ["Questionable", null, "no-projection"],
    ["NA", null, "no-projection"],
    // The doubt with the number still published is the league's own guess that he plays.
    ["Doubtful", 8.5, null],
    ["Questionable", 9.4, null],
    // No flag at all and no number is missing data, which is the `partial` chip's job.
    [null, null, null],
    ["", null, null],
    // A word this build has never seen never takes a starter out of a lineup.
    ["Sprained", null, null],
  ])("reads %s with projection %s as %s", (status, projection, expected) => {
    expect(outReason(status, projection)).toBe(expected);
    expect(isOut(status, projection)).toBe(expected !== null);
  });
});

describe("outStarters", () => {
  it("names the out starters, in lineup order, with their statuses", () => {
    const rows = withRow(
      withRow(
        healthyLineup(),
        5,
        filled("TE", {
          sleeperPlayerId: "te",
          fullName: "Broken Tightend",
          slotIndex: 5,
          injuryStatus: "Out",
          projectedPoints: null,
        }),
      ),
      2,
      filled("RB", {
        sleeperPlayerId: "rb",
        fullName: "Shelved Back",
        slotIndex: 2,
        injuryStatus: "IR",
      }),
    );
    expect(outStarters(rows)).toEqual([
      {
        sleeperPlayerId: "rb",
        fullName: "Shelved Back",
        status: "IR",
        title: "Injured reserve",
        reason: "unavailable",
        // Sleeper is still publishing a number for him; the caller has to know, because that
        // number is inside `starters_projected` and is not coverage of a lineup he is not in.
        projectedPoints: 9.4,
      },
      {
        sleeperPlayerId: "te",
        fullName: "Broken Tightend",
        status: "Out",
        title: "Out",
        reason: "unavailable",
        projectedPoints: null,
      },
    ]);
  });

  it("counts neither an empty slot nor a questionable starter as out", () => {
    const rows = withRow(
      withRow(healthyLineup(), 3, empty("WR")),
      4,
      filled("WR", {
        sleeperPlayerId: "wr",
        slotIndex: 4,
        injuryStatus: "Questionable",
      }),
    );
    expect(outStarters(rows)).toEqual([]);
  });
});

interface AvailabilityCase {
  name: string;
  input: StarterAvailabilityInput;
  outCount: number;
  outChipText: string | null;
  isPartial: boolean;
  adjustedCoveragePct: number | null;
}

/** The out TE, with no projection — Ben's own card. */
const outTe = () =>
  filled("TE", {
    sleeperPlayerId: "te",
    fullName: "Broken Tightend",
    slotIndex: 5,
    injuryStatus: "Out",
    projectedPoints: null,
  });

/** An out TE Sleeper is publishing a number for anyway. */
const projectedOutTe = () =>
  filled("TE", {
    sleeperPlayerId: "te",
    fullName: "Broken Tightend",
    slotIndex: 5,
    injuryStatus: "Out",
    projectedPoints: 4.2,
  });

/** Ben's own card, 2026-09-09: flagged `Doubtful`, and Sleeper published no projection. */
const doubtfulTe = () =>
  filled("TE", {
    sleeperPlayerId: "te",
    fullName: "Doubtful Tightend",
    slotIndex: 5,
    injuryStatus: "Doubtful",
    projectedPoints: null,
  });

/** The same doubt, with the number still published. */
const projectedDoubtfulTe = () =>
  filled("TE", {
    sleeperPlayerId: "te",
    fullName: "Doubtful Tightend",
    slotIndex: 5,
    injuryStatus: "Doubtful",
    projectedPoints: 8.5,
  });

/** A questionable starter Sleeper has stopped projecting. */
const questionableWr = () =>
  filled("WR", {
    sleeperPlayerId: "wr",
    fullName: "Questionable Receiver",
    slotIndex: 3,
    injuryStatus: "Questionable",
    projectedPoints: null,
  });

/** A fit starter Sleeper simply has no number for. */
const unprojectedStarter = () =>
  filled("WR", {
    sleeperPlayerId: "wr",
    fullName: "Unprojected Receiver",
    slotIndex: 3,
    projectedPoints: null,
  });

const AVAILABILITY_CASES: AvailabilityCase[] = [
  {
    // Ben's report: "his TE is injured with a 0 projection, and his card says `partial` as
    // if the data were missing." Nine of ten starters projected, the tenth is out.
    name: "one out starter, everyone else projected: out, never partial",
    input: {
      starterRows: withRow(healthyLineup(), 5, outTe()),
      startersProjected: 9,
      starterSlots: 10,
      emptySlots: 0,
    },
    outCount: 1,
    outChipText: "1 starter out",
    isPartial: false,
    adjustedCoveragePct: 100,
  },
  {
    // Ben's report tonight: the `Doubtful` tight end with the withdrawn projection read as
    // "missing data", which is the one case the injury work exists for.
    name: "a doubtful starter with no projection: out, never partial",
    input: {
      starterRows: withRow(healthyLineup(), 5, doubtfulTe()),
      startersProjected: 9,
      starterSlots: 10,
      emptySlots: 0,
    },
    outCount: 1,
    outChipText: "1 starter out",
    isPartial: false,
    adjustedCoveragePct: 100,
  },
  {
    name: "a doubtful starter Sleeper still projects: still available, still counted",
    input: {
      starterRows: withRow(healthyLineup(), 5, projectedDoubtfulTe()),
      startersProjected: 10,
      starterSlots: 10,
      emptySlots: 0,
    },
    outCount: 0,
    outChipText: null,
    isPartial: false,
    adjustedCoveragePct: 100,
  },
  {
    name: "a questionable starter with no projection: out on the same rule",
    input: {
      starterRows: withRow(healthyLineup(), 3, questionableWr()),
      startersProjected: 9,
      starterSlots: 10,
      emptySlots: 0,
    },
    outCount: 1,
    outChipText: "1 starter out",
    isPartial: false,
    adjustedCoveragePct: 100,
  },
  {
    name: "a healthy starter with no projection: partial, and nobody out",
    input: {
      starterRows: withRow(healthyLineup(), 3, unprojectedStarter()),
      startersProjected: 9,
      starterSlots: 10,
      emptySlots: 0,
    },
    outCount: 0,
    outChipText: null,
    isPartial: true,
    adjustedCoveragePct: 90,
  },
  {
    name: "both: the out starter is reported, and the rest is still short",
    input: {
      starterRows: withRow(
        withRow(healthyLineup(), 5, outTe()),
        3,
        unprojectedStarter(),
      ),
      startersProjected: 8,
      starterSlots: 10,
      emptySlots: 0,
    },
    outCount: 1,
    outChipText: "1 starter out",
    isPartial: true,
    adjustedCoveragePct: 88.9,
  },
  {
    // Sleeper keeps projecting some players it has already flagged. Taking the out starter out
    // of the denominator while leaving his number in the numerator credited the team for a
    // projection nobody will score: ten slots, nine projected, one of those nine a player who
    // is out and one fit starter with no number at all, and the card read 100 percent covered.
    name: "an out starter Sleeper still projects: he leaves the numerator too",
    input: {
      starterRows: withRow(
        withRow(healthyLineup(), 5, projectedOutTe()),
        3,
        unprojectedStarter(),
      ),
      startersProjected: 9,
      starterSlots: 10,
      emptySlots: 0,
    },
    outCount: 1,
    outChipText: "1 starter out",
    isPartial: true,
    adjustedCoveragePct: 88.9,
  },
  {
    name: "neither: a full, fit, fully projected lineup carries no chip at all",
    input: {
      starterRows: healthyLineup(),
      startersProjected: 10,
      starterSlots: 10,
      emptySlots: 0,
    },
    outCount: 0,
    outChipText: null,
    isPartial: false,
    adjustedCoveragePct: 100,
  },
  {
    name: "two out starters: the chip is plural",
    input: {
      starterRows: withRow(
        withRow(healthyLineup(), 5, outTe()),
        2,
        filled("RB", {
          sleeperPlayerId: "rb",
          fullName: "Shelved Back",
          slotIndex: 2,
          injuryStatus: "IR",
          projectedPoints: null,
        }),
      ),
      startersProjected: 8,
      starterSlots: 10,
      emptySlots: 0,
    },
    outCount: 2,
    outChipText: "2 starters out",
    isPartial: false,
    adjustedCoveragePct: 100,
  },
  {
    name: "an empty slot is nobody's coverage failure either",
    input: {
      starterRows: withRow(healthyLineup(), 7, empty("FLEX")),
      startersProjected: 9,
      starterSlots: 10,
      emptySlots: 1,
    },
    outCount: 0,
    outChipText: null,
    isPartial: false,
    adjustedCoveragePct: 100,
  },
  {
    name: "no projection row for the week: no counts, so no partial claim",
    input: {
      starterRows: withRow(healthyLineup(), 5, outTe()),
      startersProjected: null,
      starterSlots: null,
      emptySlots: 0,
    },
    outCount: 1,
    outChipText: "1 starter out",
    isPartial: false,
    adjustedCoveragePct: null,
  },
  {
    name: "a lineup that is entirely out or empty: nothing left to cover",
    input: {
      starterRows: [outTe(), empty("FLEX")],
      startersProjected: 0,
      starterSlots: 2,
      emptySlots: 1,
    },
    outCount: 1,
    outChipText: "1 starter out",
    isPartial: false,
    adjustedCoveragePct: 100,
  },
];

describe.each(AVAILABILITY_CASES)(
  "resolveStarterAvailability: $name",
  ({ input, outCount, outChipText, isPartial, adjustedCoveragePct }) => {
    it("counts the out starters and the coverage that is left", () => {
      const availability = resolveStarterAvailability(input);
      expect(availability.outCount).toBe(outCount);
      expect(availability.outStarters).toHaveLength(outCount);
      expect(availability.outChipText).toBe(outChipText);
      expect(availability.isPartial).toBe(isPartial);
      expect(
        availability.adjustedCoveragePct === null
          ? null
          : Number(availability.adjustedCoveragePct.toFixed(1)),
      ).toBe(adjustedCoveragePct);
    });

    it("does not mutate its input", () => {
      const before = JSON.stringify(input);
      resolveStarterAvailability(input);
      expect(JSON.stringify(input)).toBe(before);
    });
  },
);

describe("resolveStarterAvailability details", () => {
  it("names the out starters and their statuses in the chip's tooltip", () => {
    const availability = resolveStarterAvailability({
      starterRows: withRow(healthyLineup(), 5, outTe()),
      startersProjected: 9,
      starterSlots: 10,
      emptySlots: 0,
    });
    expect(availability.outChipTitle).toBe(
      "Out starters: Broken Tightend (Out)",
    );
  });

  it("says what gave a withdrawn projection away in the tooltip", () => {
    const availability = resolveStarterAvailability({
      starterRows: withRow(healthyLineup(), 5, doubtfulTe()),
      startersProjected: 9,
      starterSlots: 10,
      emptySlots: 0,
    });
    // The status alone would read as a doubt the reader could argue with; the missing number
    // is the half of the reason that makes the chip make sense.
    expect(availability.outChipTitle).toBe(
      "Out starters: Doubtful Tightend (Doubtful, no projection)",
    );
    expect(availability.outStarters[0]).toMatchObject({
      status: "Doubtful",
      title: "Doubtful",
      reason: "no-projection",
      projectedPoints: null,
    });
  });

  it("has no tooltip when nobody is out", () => {
    const availability = resolveStarterAvailability({
      starterRows: healthyLineup(),
      startersProjected: 10,
      starterSlots: 10,
      emptySlots: 0,
    });
    expect(availability.outChipTitle).toBeNull();
  });

  it("measures against the same 95 gate the data layer uses", () => {
    // 19 of 20 is 95 exactly, which clears the gate; 18 of 20 does not.
    const at = resolveStarterAvailability({
      starterRows: [],
      startersProjected: 19,
      starterSlots: 20,
      emptySlots: 0,
    });
    expect(at.adjustedCoveragePct).toBe(COVERAGE_GATE_PCT);
    expect(at.isPartial).toBe(false);
    expect(
      resolveStarterAvailability({
        starterRows: [],
        startersProjected: 18,
        starterSlots: 20,
        emptySlots: 0,
      }).isPartial,
    ).toBe(true);
  });
});
