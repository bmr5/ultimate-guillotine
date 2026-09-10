/**
 * How the FAAB figure is spelled. A pure function over a nullable number.
 *
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import { FAAB_UNKNOWN_TEXT, formatFaab } from "./faab";

describe("formatFaab", () => {
  // Ben (2026-09-10): "just put the number and $".
  it("spells the budget as a dollar amount with no unit word", () => {
    expect(formatFaab(715)).toBe("$715");
    expect(formatFaab(0)).toBe("$0");
  });

  it("keeps the sign on an unknown figure rather than showing a zero", () => {
    expect(formatFaab(null)).toBe(FAAB_UNKNOWN_TEXT);
    expect(FAAB_UNKNOWN_TEXT).toBe("$—");
  });
});
