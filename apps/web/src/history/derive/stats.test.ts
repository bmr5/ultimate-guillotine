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
  faabTotal: 10,
  confidence: "high",
  sourceLabel: "catalog",
  registered: false,
  rescinded: false,
  unresolvedParties: 0,
};

describe("tradeStats", () => {
  it("sums FAAB, counts seasons, and names the most-traded position", () => {
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
        faabTotal: null,
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
      faabMoved: 10,
      topPosition: "RB",
    });
  });

  it("reports no position when nothing has one", () => {
    expect(tradeStats([base]).topPosition).toBeNull();
  });

  it("leaves a rescinded trade's FAAB out of the total", () => {
    const stats = tradeStats([
      base,
      { ...base, key: "k2", faabTotal: 40, rescinded: true },
    ]);
    // Both trades are still counted and still shown; only the money that never moved is out.
    expect(stats.tradeCount).toBe(2);
    expect(stats.faabMoved).toBe(10);
  });
});
