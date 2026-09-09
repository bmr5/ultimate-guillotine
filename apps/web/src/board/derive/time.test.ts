/**
 * These helpers are pure and touch no DOM, so they run under node; jsdom stays the default for
 * component tests. Node also gives `Intl` exactly the ICU data production runs on.
 *
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import {
  crossesMinuteBoundary,
  formatUpdatedAgo,
  formatUpdatedAt,
  formatUpdatedTitle,
  isStale,
  MS_PER_MINUTE,
  NEVER_UPDATED_AGO_LABEL,
  NEVER_UPDATED_LABEL,
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

  it("decides today by the injected zone, not UTC, when the two disagree", () => {
    // Still Sep 9 in UTC, but 10:00 PM on Sep 8 in New York — so a New York viewer must see the
    // date. A UTC-based comparison would wrongly print the bare clock time.
    const lateOnTheEighth = Date.UTC(2026, 8, 9, 2, 0);
    expect(plain(formatUpdatedAt(lateOnTheEighth, NOW, NY))).toBe("Updated Sep 8, 10:00 PM");
  });

  it("counts local midnight as today", () => {
    const midnightInNY = Date.UTC(2026, 8, 9, 4, 0);
    expect(plain(formatUpdatedAt(midnightInNY, NOW, NY))).toBe("Updated 12:00 AM");
  });

  it("counts the last minute of the local day as today, though UTC has rolled over", () => {
    // 11:59 PM on Sep 9 in New York is already Sep 10 in UTC.
    const lastMinuteInNY = Date.UTC(2026, 8, 10, 3, 59);
    expect(plain(formatUpdatedAt(lastMinuteInNY, NOW, NY))).toBe("Updated 11:59 PM");
  });

  it("says so plainly when nothing has been pulled", () => {
    expect(formatUpdatedAt(null, NOW, NY)).toBe(NEVER_UPDATED_LABEL);
    expect(formatUpdatedAt(null, NOW, NY)).toBe("Not updated yet");
  });

  it("treats an unfetched query's zero and undefined as never pulled", () => {
    // TanStack Query reports dataUpdatedAt as 0 before the first fetch resolves; unguarded it
    // would render as the epoch.
    expect(formatUpdatedAt(0, NOW, NY)).toBe(NEVER_UPDATED_LABEL);
    expect(formatUpdatedAt(undefined, NOW, NY)).toBe(NEVER_UPDATED_LABEL);
  });
});

describe("formatUpdatedTitle", () => {
  it("spells the instant out in words, never as an ISO string", () => {
    const title = plain(formatUpdatedTitle(NOW, NY));
    expect(title).toBe("Updated Wednesday, September 9, 2026 at 12:41 PM");
    expect(title).not.toMatch(/\d{4}-\d{2}-\d{2}T/);
  });

  it("matches formatUpdatedAt's empty state", () => {
    expect(formatUpdatedTitle(null, NY)).toBe(NEVER_UPDATED_LABEL);
    expect(formatUpdatedTitle(0, NY)).toBe(NEVER_UPDATED_LABEL);
    expect(formatUpdatedTitle(undefined, NY)).toBe(NEVER_UPDATED_LABEL);
  });
});

describe("formatUpdatedAgo", () => {
  it("says never when nothing has loaded", () => {
    expect(formatUpdatedAgo(null, NOW)).toBe(NEVER_UPDATED_AGO_LABEL);
    expect(formatUpdatedAgo(null, NOW)).toBe("never");
  });

  it("says never for an unfetched query rather than counting from the epoch", () => {
    expect(formatUpdatedAgo(0, NOW)).toBe(NEVER_UPDATED_AGO_LABEL);
    expect(formatUpdatedAgo(undefined, NOW)).toBe(NEVER_UPDATED_AGO_LABEL);
  });

  it("says just now under five seconds", () => {
    expect(formatUpdatedAgo(NOW - 2_000, NOW)).toBe("just now");
  });

  it("holds just now up to the five-second edge and counts from it", () => {
    expect(formatUpdatedAgo(NOW - 4_999, NOW)).toBe("just now");
    expect(formatUpdatedAgo(NOW - 5_000, NOW)).toBe("5 sec ago");
  });

  it("counts seconds up to ninety", () => {
    expect(formatUpdatedAgo(NOW - 45_000, NOW)).toBe("45 sec ago");
    expect(formatUpdatedAgo(NOW - 89_000, NOW)).toBe("89 sec ago");
  });

  it("switches to minutes exactly at ninety seconds", () => {
    expect(formatUpdatedAgo(NOW - 89_999, NOW)).toBe("89 sec ago");
    expect(formatUpdatedAgo(NOW - 90_000, NOW)).toBe("1 min ago");
    expect(formatUpdatedAgo(NOW - 125_000, NOW)).toBe("2 min ago");
  });

  it("switches to hours exactly at ninety minutes", () => {
    expect(formatUpdatedAgo(NOW - 89 * MS_PER_MINUTE, NOW)).toBe("89 min ago");
    expect(formatUpdatedAgo(NOW - 90 * MS_PER_MINUTE, NOW)).toBe("1 hr ago");
    expect(formatUpdatedAgo(NOW - 3 * 60 * 60_000, NOW)).toBe("3 hr ago");
  });

  it("never reports a negative age when the clock jitters", () => {
    expect(formatUpdatedAgo(NOW + 5_000, NOW)).toBe("just now");
    expect(formatUpdatedAgo(NOW + 5 * MS_PER_MINUTE, NOW)).toBe("just now");
  });
});

describe("isStale", () => {
  it("is stale past thirty minutes", () => {
    expect(isStale(NOW - STALE_AFTER_MS - 1, NOW)).toBe(true);
  });

  it("is fresh exactly at the threshold", () => {
    expect(isStale(NOW - STALE_AFTER_MS, NOW)).toBe(false);
  });

  it("is fresh inside thirty minutes", () => {
    expect(isStale(NOW - 29 * 60_000, NOW)).toBe(false);
  });

  it("is fresh when the clock jitters the timestamp into the future", () => {
    expect(isStale(NOW + 5 * MS_PER_MINUTE, NOW)).toBe(false);
  });

  it("treats never-loaded as stale", () => {
    expect(isStale(null, NOW)).toBe(true);
  });

  it("treats an unfetched query as stale rather than ancient", () => {
    expect(isStale(0, NOW)).toBe(true);
    expect(isStale(undefined, NOW)).toBe(true);
  });
});

describe("crossesMinuteBoundary", () => {
  it("is true only when the whole-minute count changes", () => {
    expect(crossesMinuteBoundary(59_999, 60_001)).toBe(true);
    expect(crossesMinuteBoundary(1_000, 2_000)).toBe(false);
  });

  it("stays quiet across the sub-90-second ticks, which are deliberately not announced", () => {
    expect(crossesMinuteBoundary(45_000, 46_000)).toBe(false);
    expect(crossesMinuteBoundary(88_000, 89_000)).toBe(false);
  });
});

describe("named constants", () => {
  it("keeps the tick fine enough to catch every minute boundary", () => {
    expect(TICK_INTERVAL_MS).toBeLessThanOrEqual(MS_PER_MINUTE);
    expect(STALE_AFTER_MS).toBe(30 * MS_PER_MINUTE);
  });
});
