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
  parties: [{ memberId: 1, label: "Alpha", resolved: true }],
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
  announcement: null,
  confidence: "high",
  registeredAt: null,
  announcedBy: null,
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

  // The announcement is on the card, so the search box has to find what the card shows. The
  // text here is invented; nothing the league said appears in this file.
  it("matches the announcement text, tokenised the same way", () => {
    const announced: CatalogTrade = {
      ...TRADE,
      announcement: "ANNOUNCEMENT-ONE: a rentál for the bye week",
    };
    expect(
      filterTrades([announced], { ...EMPTY_FILTERS, search: "rental" }),
    ).toEqual([announced]);
    expect(
      filterTrades([announced], { ...EMPTY_FILTERS, search: "bye rental" }),
    ).toEqual([announced]);
    // Every word still has to land, and a trade with no announcement has nothing to land in.
    expect(
      filterTrades([announced], { ...EMPTY_FILTERS, search: "rental keeper" }),
    ).toEqual([]);
    expect(
      filterTrades([{ ...announced, announcement: null }], {
        ...EMPTY_FILTERS,
        search: "rental",
      }),
    ).toEqual([]);
  });

  // Two haystacks, not one pooled one: a word from the announcement and a word from a player's
  // name are not a match, or the all-words rule would mean nothing on this page.
  it("does not pool the announcement and the player names into one haystack", () => {
    const announced: CatalogTrade = {
      ...TRADE,
      announcement: "ANNOUNCEMENT-ONE: a rental for the bye week",
    };
    expect(
      filterTrades([announced], { ...EMPTY_FILTERS, search: "player" }),
    ).toEqual([announced]);
    expect(
      filterTrades([announced], { ...EMPTY_FILTERS, search: "player rental" }),
    ).toEqual([]);
  });

  it("matches every word of the term in any order, as the board does", () => {
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
      filterTrades([accented], { ...EMPTY_FILTERS, search: "nacua puka" }),
    ).toEqual([accented]);
    expect(
      filterTrades([accented], { ...EMPTY_FILTERS, search: "puka nacua" }),
    ).toEqual([accented]);
    // Every word still has to land in the same player: one hit is not a match.
    expect(
      filterTrades([accented], { ...EMPTY_FILTERS, search: "puka allen" }),
    ).toEqual([]);
  });
});
