/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { CatalogTrade } from "../types";
import { tradeDateLine } from "./tradeDate";

/**
 * Both halves of the line depend on the reader's clock settings, so every case pins them. The
 * app passes neither, which is how a card shows a New York evening to a reader in New York.
 */
const IN_NEW_YORK = { locales: "en-US", timeZone: "America/New_York" };

const CATALOG: CatalogTrade = {
  key: "catalog:1",
  season: 2024,
  week: 3,
  occurredOn: null,
  tradeType: "rental",
  structure: "2-team",
  parties: [],
  partyCount: 2,
  assets: [],
  confidence: "high",
  announcement: null,
  registeredAt: null,
  sourceLabel: "catalog",
  registered: false,
  rescinded: false,
  unresolvedParties: 0,
};

const REGISTERED: CatalogTrade = {
  ...CATALOG,
  key: "registered:5",
  season: 2026,
  registeredAt: "2026-09-10T01:12:00Z",
  sourceLabel: "T-2026-014",
  registered: true,
};

describe("tradeDateLine", () => {
  // Ben's ruling of 2026-09-09: a card logs "the Participants, the date and time, a category,
  // and the exact text". A registered trade knows the instant it was recorded, so it says so.
  it("dates a registered trade by the instant it was recorded", () => {
    expect(tradeDateLine(REGISTERED, IN_NEW_YORK)).toBe(
      "Sep 9, 2026 · 9:12 PM",
    );
  });

  // The stamp is stored in UTC and read in the viewer's zone: the same instant is the 9th in
  // New York and the 10th in Berlin, and each reader sees his own day.
  it("reads the stamp in the viewer's own timezone", () => {
    expect(
      tradeDateLine(REGISTERED, {
        locales: "en-GB",
        timeZone: "Europe/Berlin",
      }),
    ).toBe("10 Sept 2026 · 3:12");
  });

  // The catalog is a reading of a spreadsheet: it knows a season and a week and no clock time,
  // so its cards keep saying that rather than having one invented for them.
  it("dates a catalog row by its season and week", () => {
    expect(tradeDateLine(CATALOG, IN_NEW_YORK)).toBe("Season 2024 · Week 3");
  });

  it("uses the day for a catalog row the sheet placed by date", () => {
    expect(
      tradeDateLine(
        { ...CATALOG, week: null, occurredOn: "2024-09-30" },
        IN_NEW_YORK,
      ),
    ).toBe("Season 2024 · 2024-09-30");
  });

  it("says the season alone when the row knows nothing finer", () => {
    expect(
      tradeDateLine({ ...CATALOG, week: null, occurredOn: null }, IN_NEW_YORK),
    ).toBe("Season 2024");
  });

  // A card that quietly loses a line is a better failure than one printing `Invalid Date`.
  it("falls back to the season form for a stamp it cannot parse", () => {
    expect(
      tradeDateLine({ ...REGISTERED, registeredAt: "not a date" }, IN_NEW_YORK),
    ).toBe("Season 2026 · Week 3");
  });
});
