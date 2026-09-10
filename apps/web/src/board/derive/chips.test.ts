import { describe, expect, it } from "vitest";

import { MAX_CHIPS, resolveChipKinds, type ChipSetInput } from "./chips";

/** A live, fully projected, fully fit card: the state every case below departs from. */
const base: ChipSetInput = {
  isEliminated: false,
  hasProjection: true,
  outCount: 0,
  isPartial: false,
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

  it("leaves a card with nothing to say bare", () => {
    expect(resolveChipKinds(input())).toEqual([]);
  });

  it("shows each live chip on its own when only one is true", () => {
    expect(resolveChipKinds(input({ outCount: 1 }))).toEqual(["out"]);
    expect(resolveChipKinds(input({ isPartial: true }))).toEqual(["partial"]);
  });

  // The whole point of the rule: the owner's name reserves against this number, and the reserve
  // is only honest if nothing can exceed it.
  it("never returns more chips than the reserve is measured for", () => {
    for (const isEliminated of [false, true]) {
      for (const hasProjection of [false, true]) {
        for (const outCount of [0, 1, 2]) {
          for (const isPartial of [false, true]) {
            const kinds = resolveChipKinds({
              isEliminated,
              hasProjection,
              outCount,
              isPartial,
            });
            expect(kinds.length).toBeLessThanOrEqual(MAX_CHIPS);
            // And never the same chip twice, which a reserve by count would also under-measure.
            expect(new Set(kinds).size).toBe(kinds.length);
          }
        }
      }
    }
  });
});
