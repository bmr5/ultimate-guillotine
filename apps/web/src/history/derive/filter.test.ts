import { describe, expect, it } from "vitest";

import type { CatalogTrade } from "../types";
import { EMPTY_FILTERS } from "../types";
import { filterTrades } from "./filter";

const TRADE: CatalogTrade = {
  key: "catalog:1",
  season: 2025,
  week: 3,
  occurredOn: null,
  tradeType: "rental",
  structure: "player-for-faab",
  parties: [{ memberId: 1, label: "Alpha" }],
  partyCount: 2,
  assets: [
    {
      kind: "player",
      playerId: "1",
      name: "A Player",
      position: "RB",
      fromParty: 0,
      toParty: 1,
    },
  ],
  faabTotal: 12,
  confidence: "high",
  sourceLabel: "catalog",
  registered: false,
  rescinded: false,
  unresolvedParties: 1,
};

describe("filterTrades", () => {
  it("combines every filter with AND", () => {
    const other: CatalogTrade = {
      ...TRADE,
      key: "catalog:2",
      season: 2024,
      tradeType: "trade",
    };
    const trades = [TRADE, other];

    expect(
      filterTrades(trades, {
        season: 2025,
        type: null,
        position: null,
        memberId: null,
        search: "",
      }),
    ).toEqual([TRADE]);
    expect(
      filterTrades(trades, {
        season: 2025,
        type: "trade",
        position: null,
        memberId: null,
        search: "",
      }),
    ).toEqual([]);
    expect(
      filterTrades(trades, {
        season: null,
        type: null,
        position: "RB",
        memberId: 1,
        search: "play",
      }),
    ).toEqual([TRADE, other]);
    expect(
      filterTrades(trades, {
        season: null,
        type: null,
        position: "QB",
        memberId: null,
        search: "",
      }),
    ).toEqual([]);
  });

  it("matches the member filter against resolved parties only", () => {
    expect(
      filterTrades([TRADE], {
        season: null,
        type: null,
        position: null,
        memberId: 9,
        search: "",
      }),
    ).toEqual([]);
  });

  it("folds accents and punctuation the way the board search does", () => {
    const accented: CatalogTrade = {
      ...TRADE,
      assets: [
        {
          kind: "player",
          playerId: "2",
          name: "Puka Nacuá",
          position: "WR",
          fromParty: 0,
          toParty: 1,
        },
      ],
    };
    expect(
      filterTrades([accented], { ...EMPTY_FILTERS, search: "Nacua" }),
    ).toEqual([accented]);
    expect(
      filterTrades([accented], { ...EMPTY_FILTERS, search: "  NACUÁ " }),
    ).toEqual([accented]);
  });
});
