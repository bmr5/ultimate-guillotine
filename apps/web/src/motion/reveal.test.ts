/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import {
  REVEAL_CLASS,
  REVEAL_INDEX_PROPERTY,
  REVEAL_STAGGER_CAP,
  revealStyle,
} from "./reveal";

describe("revealStyle", () => {
  it("hands the element its place in the cascade as a custom property", () => {
    expect(revealStyle(3)).toEqual({ [REVEAL_INDEX_PROPERTY]: 3 });
  });

  it("caps the place so a long list does not trail in one card at a time", () => {
    expect(revealStyle(REVEAL_STAGGER_CAP + 40)).toEqual({
      [REVEAL_INDEX_PROPERTY]: REVEAL_STAGGER_CAP,
    });
  });

  it("treats a negative or fractional place as the front of the cascade", () => {
    expect(revealStyle(-2)).toEqual({ [REVEAL_INDEX_PROPERTY]: 0 });
    expect(revealStyle(1.7)).toEqual({ [REVEAL_INDEX_PROPERTY]: 1 });
  });

  it("names the class the stylesheet hangs the cascade off", () => {
    expect(REVEAL_CLASS).toBe("reveal");
    expect(REVEAL_INDEX_PROPERTY).toBe("--reveal-index");
  });
});
