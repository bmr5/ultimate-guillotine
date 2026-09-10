/** @vitest-environment node */
import { describe, expect, it } from "vitest";

import { formatDateLine } from "./dateLine";

const OPTIONS = { locales: "en-US", timeZone: "America/Chicago" };

describe("formatDateLine", () => {
  it("is the day and the week, in the trade page's voice", () => {
    expect(formatDateLine("2026-09-08T14:01:40Z", 1, OPTIONS)).toBe(
      "Sep 8 · Wk 1",
    );
  });

  it("is the day alone when there is no week", () => {
    expect(formatDateLine("2026-09-07T23:01:30.433Z", null, OPTIONS)).toBe(
      "Sep 7",
    );
  });

  it("falls back to the week alone for an unparseable instant", () => {
    expect(formatDateLine("not a date", 4, OPTIONS)).toBe("Wk 4");
    expect(formatDateLine("not a date", null, OPTIONS)).toBe("");
  });
});
