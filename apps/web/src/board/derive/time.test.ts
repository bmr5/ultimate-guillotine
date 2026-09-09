import { describe, expect, it } from "vitest";

import {
  crossesMinuteBoundary,
  formatUpdatedAgo,
  formatUpdatedAt,
  formatUpdatedTitle,
  isStale,
  MS_PER_MINUTE,
  STALE_AFTER_MS,
  TICK_INTERVAL_MS,
  type TimeFormatOptions,
} from "./time";

/** 2026-09-09T16:41:20Z — 12:41 PM in New York. */
const NOW = 1_788_972_080_000;

/** Node's ICU puts U+202F before AM/PM; the assertions compare plain spaces. */
const plain = (value: string) => value.replace(/[\u202f\u00a0]/g, " ");

const NY: TimeFormatOptions = { locales: "en-US", timeZone: "America/New_York" };

describe("formatUpdatedAt", () => {
  it("shows a clock time alone for a pull made today, in the viewer's zone", () => {
    expect(plain(formatUpdatedAt(NOW, NOW, NY))).toBe("Updated 12:41 PM");
  });

  it("renders the same instant in the viewer's own timezone", () => {
    expect(
      plain(formatUpdatedAt(NOW, NOW, { locales: "en-US", timeZone: "America/Los_Angeles" })),
    ).toBe("Updated 9:41 AM");
  });

  it("prefixes the date once the pull is not today", () => {
    const yesterday = NOW - 24 * 60 * 60 * 1000;
    expect(plain(formatUpdatedAt(yesterday, NOW, NY))).toBe("Updated Sep 8, 12:41 PM");
  });

  it("says so plainly when nothing has been pulled", () => {
    expect(formatUpdatedAt(null, NOW, NY)).toBe("Not updated yet");
  });
});

describe("formatUpdatedTitle", () => {
  it("spells the instant out in words, never as an ISO string", () => {
    const title = plain(formatUpdatedTitle(NOW, NY));
    expect(title).toBe("Updated Wednesday, September 9, 2026 at 12:41 PM");
    expect(title).not.toMatch(/\d{4}-\d{2}-\d{2}T/);
  });

  it("matches formatUpdatedAt's empty state", () => {
    expect(formatUpdatedTitle(null, NY)).toBe("Not updated yet");
  });
});

describe("formatUpdatedAgo", () => {
  it("says never when nothing has loaded", () => {
    expect(formatUpdatedAgo(null, NOW)).toBe("never");
  });

  it("says just now under five seconds", () => {
    expect(formatUpdatedAgo(NOW - 2_000, NOW)).toBe("just now");
  });

  it("counts seconds up to ninety", () => {
    expect(formatUpdatedAgo(NOW - 45_000, NOW)).toBe("45 sec ago");
    expect(formatUpdatedAgo(NOW - 89_000, NOW)).toBe("89 sec ago");
  });

  it("switches to minutes past ninety seconds", () => {
    expect(formatUpdatedAgo(NOW - 90_000, NOW)).toBe("1 min ago");
    expect(formatUpdatedAgo(NOW - 125_000, NOW)).toBe("2 min ago");
  });

  it("switches to hours past ninety minutes", () => {
    expect(formatUpdatedAgo(NOW - 3 * 60 * 60_000, NOW)).toBe("3 hr ago");
  });

  it("never reports a negative age when the clock jitters", () => {
    expect(formatUpdatedAgo(NOW + 5_000, NOW)).toBe("just now");
  });
});

describe("isStale", () => {
  it("is stale past thirty minutes", () => {
    expect(isStale(NOW - STALE_AFTER_MS - 1, NOW)).toBe(true);
  });

  it("is fresh inside thirty minutes", () => {
    expect(isStale(NOW - 29 * 60_000, NOW)).toBe(false);
  });

  it("treats never-loaded as stale", () => {
    expect(isStale(null, NOW)).toBe(true);
  });
});

describe("crossesMinuteBoundary", () => {
  it("is true only when the whole-minute count changes", () => {
    expect(crossesMinuteBoundary(59_999, 60_001)).toBe(true);
    expect(crossesMinuteBoundary(1_000, 2_000)).toBe(false);
  });
});

describe("named constants", () => {
  it("keeps the tick fine enough to catch every minute boundary", () => {
    expect(TICK_INTERVAL_MS).toBeLessThanOrEqual(MS_PER_MINUTE);
    expect(STALE_AFTER_MS).toBe(30 * MS_PER_MINUTE);
  });
});
