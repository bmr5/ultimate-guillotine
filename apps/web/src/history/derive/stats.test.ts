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
  sourceLabel: "catalog",
  registered: false,
  rescinded: false,
  unresolvedParties: 0,
};

describe("tradeStats", () => {
  // Three figures, not four. `faabMoved` went with the card's FAAB badge, by Ben's ruling of
  // 2026-09-09 that the number is not a useful thing to log for these deals; the equality below
  // is against the whole object rather than field by field so a fourth cannot creep back in
  // unnoticed.
  it("counts trades and seasons, and names the most-traded position", () => {
    const stats = tradeStats([
      {
        ...base,
        assets: [
          {
            kind: "player",
            playerId: "1",
            name: "P",
            position: "RB",
            fromParty: 0,
            toParty: 1,
          },
        ],
      },
      {
        ...base,
        key: "k2",
        season: 2024,
        assets: [
          {
            kind: "player",
            playerId: "2",
            name: "Q",
            position: "RB",
            fromParty: 0,
            toParty: 1,
          },
          {
            kind: "player",
            playerId: "3",
            name: "R",
            position: "WR",
            fromParty: 1,
            toParty: 0,
          },
        ],
      },
    ]);
    expect(stats).toEqual({
      tradeCount: 2,
      seasonCount: 2,
      topPosition: "RB",
    });
  });

  it("reports no position when nothing has one", () => {
    expect(tradeStats([base]).topPosition).toBeNull();
  });

  // A rescinded trade happened, so it is counted and shown like any other.
  it("counts a rescinded trade", () => {
    const stats = tradeStats([base, { ...base, key: "k2", rescinded: true }]);
    expect(stats.tradeCount).toBe(2);
  });
});
