import { describe, expect, it } from "vitest";

import {
  MAX_CHIPS,
  resolveChipKinds,
  type ChipKind,
  type ChipSetInput,
} from "./chips";

/** A live, fully projected, fully fit card: the state every case below departs from. */
const base: ChipSetInput = {
  isEliminated: false,
  hasProjection: true,
  outCount: 0,
  isPartial: false,
  hasOdds: false,
};

const input = (over: Partial<ChipSetInput> = {}): ChipSetInput => ({
  ...base,
  ...over,
});

/**
 * The ruling after fix round 2: the chip set is mutually limited. Four cases, which is the whole
 * rule — an eliminated card, a card with no projection, the live card that can carry two, and
 * the quiet card that carries none.
 */
describe("resolveChipKinds", () => {
  it("says only that an eliminated team is eliminated", () => {
    // Everything else is true of this card as well, and none of it belongs beside the ruling:
    // a frozen projection has no live coverage to caveat.
    expect(
      resolveChipKinds(
        input({
          isEliminated: true,
          hasProjection: false,
          outCount: 2,
          isPartial: true,
          hasOdds: true,
        }),
      ),
    ).toEqual(["eliminated"]);
  });

  it("says only that a projection is unavailable when there is no number", () => {
    // An out starter is a footnote on a projection; with no projection there is nothing to
    // footnote, and `2 starters out` beside an em dash implies the number was adjusted for it.
    expect(
      resolveChipKinds(
        input({ hasProjection: false, outCount: 2, isPartial: true }),
      ),
    ).toEqual(["unavailable"]);
  });

  it("puts the out starters before the caveat on a live card", () => {
    expect(resolveChipKinds(input({ outCount: 2, isPartial: true }))).toEqual([
      "out",
      "partial",
    ]);
  });

  it("leads a live card with the odds, ahead of the roster and the caveat", () => {
    // The Daily's headline number comes first; what is happening to the roster and the
    // footnote on the projection follow it in the order they already had.
    expect(
      resolveChipKinds(input({ hasOdds: true, outCount: 2, isPartial: true })),
    ).toEqual(["odds", "out", "partial"]);
  });

  it("keeps the odds beside a missing projection", () => {
    // The odds are the Daily's own number, not a caveat on Sleeper's, so an em dash beside
    // them does not make them a footnote on nothing.
    expect(
      resolveChipKinds(input({ hasOdds: true, hasProjection: false })),
    ).toEqual(["odds", "unavailable"]);
  });

  it("fills the line exactly to the cap on the fullest live card", () => {
    expect(
      resolveChipKinds(input({ hasOdds: true, outCount: 1, isPartial: true })),
    ).toHaveLength(MAX_CHIPS);
  });

  it("leaves a card with nothing to say bare", () => {
    expect(resolveChipKinds(input())).toEqual([]);
  });

  it("shows each live chip on its own when only one is true", () => {
    expect(resolveChipKinds(input({ outCount: 1 }))).toEqual(["out"]);
    expect(resolveChipKinds(input({ isPartial: true }))).toEqual(["partial"]);
  });
});

/**
 * Every state the five inputs can be in, with the exact chips each one is allowed to say.
 *
 * Exhaustive and spelled out rather than swept for a property: a sweep that only checked the
 * count would pass on `["eliminated", "partial"]`, which is the wording bug the rule exists to
 * prevent, not merely a line that got too long. Forty-eight rows is the whole input space —
 * two eliminations × two projections × three out-counts × two caveats, each with and without
 * the odds — so a rule change has to come here and say what it now means. The twenty-four rows
 * below are the four original inputs; `CASES` doubles them over the odds, row by row.
 */
const BASE_CASES: {
  name: string;
  input: Omit<ChipSetInput, "hasOdds">;
  expected: ChipKind[];
}[] = [
  {
    name: "live, no projection, 0 out, whole",
    input: {
      isEliminated: false,
      hasProjection: false,
      outCount: 0,
      isPartial: false,
    },
    expected: ["unavailable"],
  },
  {
    name: "live, no projection, 0 out, partial",
    input: {
      isEliminated: false,
      hasProjection: false,
      outCount: 0,
      isPartial: true,
    },
    expected: ["unavailable"],
  },
  {
    name: "live, no projection, 1 out, whole",
    input: {
      isEliminated: false,
      hasProjection: false,
      outCount: 1,
      isPartial: false,
    },
    expected: ["unavailable"],
  },
  {
    name: "live, no projection, 1 out, partial",
    input: {
      isEliminated: false,
      hasProjection: false,
      outCount: 1,
      isPartial: true,
    },
    expected: ["unavailable"],
  },
  {
    name: "live, no projection, 2 out, whole",
    input: {
      isEliminated: false,
      hasProjection: false,
      outCount: 2,
      isPartial: false,
    },
    expected: ["unavailable"],
  },
  {
    name: "live, no projection, 2 out, partial",
    input: {
      isEliminated: false,
      hasProjection: false,
      outCount: 2,
      isPartial: true,
    },
    expected: ["unavailable"],
  },
  {
    name: "live, projected, 0 out, whole",
    input: {
      isEliminated: false,
      hasProjection: true,
      outCount: 0,
      isPartial: false,
    },
    expected: [],
  },
  {
    name: "live, projected, 0 out, partial",
    input: {
      isEliminated: false,
      hasProjection: true,
      outCount: 0,
      isPartial: true,
    },
    expected: ["partial"],
  },
  {
    name: "live, projected, 1 out, whole",
    input: {
      isEliminated: false,
      hasProjection: true,
      outCount: 1,
      isPartial: false,
    },
    expected: ["out"],
  },
  {
    name: "live, projected, 1 out, partial",
    input: {
      isEliminated: false,
      hasProjection: true,
      outCount: 1,
      isPartial: true,
    },
    expected: ["out", "partial"],
  },
  {
    name: "live, projected, 2 out, whole",
    input: {
      isEliminated: false,
      hasProjection: true,
      outCount: 2,
      isPartial: false,
    },
    expected: ["out"],
  },
  {
    name: "live, projected, 2 out, partial",
    input: {
      isEliminated: false,
      hasProjection: true,
      outCount: 2,
      isPartial: true,
    },
    expected: ["out", "partial"],
  },
  {
    name: "eliminated, no projection, 0 out, whole",
    input: {
      isEliminated: true,
      hasProjection: false,
      outCount: 0,
      isPartial: false,
    },
    expected: ["eliminated"],
  },
  {
    name: "eliminated, no projection, 0 out, partial",
    input: {
      isEliminated: true,
      hasProjection: false,
      outCount: 0,
      isPartial: true,
    },
    expected: ["eliminated"],
  },
  {
    name: "eliminated, no projection, 1 out, whole",
    input: {
      isEliminated: true,
      hasProjection: false,
      outCount: 1,
      isPartial: false,
    },
    expected: ["eliminated"],
  },
  {
    name: "eliminated, no projection, 1 out, partial",
    input: {
      isEliminated: true,
      hasProjection: false,
      outCount: 1,
      isPartial: true,
    },
    expected: ["eliminated"],
  },
  {
    name: "eliminated, no projection, 2 out, whole",
    input: {
      isEliminated: true,
      hasProjection: false,
      outCount: 2,
      isPartial: false,
    },
    expected: ["eliminated"],
  },
  {
    name: "eliminated, no projection, 2 out, partial",
    input: {
      isEliminated: true,
      hasProjection: false,
      outCount: 2,
      isPartial: true,
    },
    expected: ["eliminated"],
  },
  {
    name: "eliminated, projected, 0 out, whole",
    input: {
      isEliminated: true,
      hasProjection: true,
      outCount: 0,
      isPartial: false,
    },
    expected: ["eliminated"],
  },
  {
    name: "eliminated, projected, 0 out, partial",
    input: {
      isEliminated: true,
      hasProjection: true,
      outCount: 0,
      isPartial: true,
    },
    expected: ["eliminated"],
  },
  {
    name: "eliminated, projected, 1 out, whole",
    input: {
      isEliminated: true,
      hasProjection: true,
      outCount: 1,
      isPartial: false,
    },
    expected: ["eliminated"],
  },
  {
    name: "eliminated, projected, 1 out, partial",
    input: {
      isEliminated: true,
      hasProjection: true,
      outCount: 1,
      isPartial: true,
    },
    expected: ["eliminated"],
  },
  {
    name: "eliminated, projected, 2 out, whole",
    input: {
      isEliminated: true,
      hasProjection: true,
      outCount: 2,
      isPartial: false,
    },
    expected: ["eliminated"],
  },
  {
    name: "eliminated, projected, 2 out, partial",
    input: {
      isEliminated: true,
      hasProjection: true,
      outCount: 2,
      isPartial: true,
    },
    expected: ["eliminated"],
  },
];

/**
 * The odds dimension, exact per row: with odds, an eliminated card says what it said, and every
 * live card says `odds` first and then exactly what it said before.
 */
const CASES: { name: string; input: ChipSetInput; expected: ChipKind[] }[] =
  BASE_CASES.flatMap(({ name, input: state, expected }) => [
    { name: `${name}, no odds`, input: { ...state, hasOdds: false }, expected },
    {
      name: `${name}, odds`,
      input: { ...state, hasOdds: true },
      expected: state.isEliminated ? expected : ["odds", ...expected],
    },
  ]);

describe("resolveChipKinds over every input", () => {
  it.each(CASES)("says $expected for $name", ({ input: state, expected }) => {
    const kinds = resolveChipKinds(state);
    expect(kinds).toEqual(expected);
    // And the cap the chip line is sized for holds, case by case, so `MAX_CHIPS` cannot drift
    // away from the rule it is quoting.
    expect(kinds.length).toBeLessThanOrEqual(MAX_CHIPS);
  });
});
