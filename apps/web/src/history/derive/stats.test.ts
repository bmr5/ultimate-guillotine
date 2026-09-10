import { describe, expect, it } from "vitest";

import type { CatalogTrade } from "../types";
import { tradeStats } from "./stats";

const base: CatalogTrade = {
  key: "k1",
  season: 2025,
  week: 1,
  occurredOn: null,
  tradeType: "trade",
  structure: "1-for-1",
  parties: [],
  partyCount: 2,
  assets: [],
  confidence: "high",
  announcement: null,
  registeredAt: null,
  announcedBy: null,
  sourceLabel: "catalog",
  registered: false,
  rescinded: false,
  unresolvedParties: 0,
};

describe("tradeStats", () => {
  // Two figures. `faabMoved` went with the card's FAAB badge (Ben, 2026-09-09) and
  // `topPosition` the day after (Ben, 2026-09-10: assets are stored as words, not parsed).
  // The equality is against the whole object so a third figure cannot creep back in unnoticed.
  it("counts trades and seasons and nothing else", () => {
    const stats = tradeStats([
      base,
      { ...base, key: "k2", season: 2024 },
      { ...base, key: "k3" },
    ]);
    expect(stats).toEqual({ tradeCount: 3, seasonCount: 2 });
  });

  it("is empty for no trades", () => {
    expect(tradeStats([])).toEqual({ tradeCount: 0, seasonCount: 0 });
  });
});
