/**
 * Map lookups and arithmetic over plain rows: no DOM.
 *
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { DraftPickRow } from "../fetchers";
import type { DraftPickInfo } from "../types";
import {
  auctionContext,
  auctionContextLine,
  draftedHere,
  indexDraftPicks,
  ordinal,
} from "./draft";

const pick = (
  over: Partial<DraftPickRow> & { sleeper_player_id: string; amount: number },
): DraftPickRow => ({
  team_id: 7,
  pick_no: 1,
  round: 1,
  position: "RB",
  drafted_at: "2026-09-07T23:01:30.433Z",
  ...over,
});

const PICKS = [
  pick({ sleeper_player_id: "a", amount: 80, pick_no: 1 }),
  pick({ sleeper_player_id: "b", amount: 61, pick_no: 2, team_id: 8 }),
  pick({ sleeper_player_id: "c", amount: 61, pick_no: 3, position: "WR" }),
  pick({ sleeper_player_id: "d", amount: 12, pick_no: 4 }),
  pick({ sleeper_player_id: "e", amount: 1, pick_no: 5, position: "K" }),
];

const must = (index: Map<string, DraftPickInfo>, id: string): DraftPickInfo => {
  const info = index.get(id);
  if (info === undefined) throw new Error(`no pick ${id}`);
  return info;
};

describe("indexDraftPicks", () => {
  it("keys every pick by its player, carrying the team and the price", () => {
    const index = indexDraftPicks(PICKS);
    expect(index.get("b")).toEqual({
      teamId: 8,
      amount: 61,
      pickNo: 2,
      round: 1,
      position: "RB",
      draftedAt: "2026-09-07T23:01:30.433Z",
    });
    expect(index.size).toBe(5);
  });
});

describe("draftedHere", () => {
  it("is true only when the pick belongs to the row's team", () => {
    const index = indexDraftPicks(PICKS);
    expect(draftedHere(index.get("a") ?? null, 7)).toBe(true);
    expect(draftedHere(index.get("b") ?? null, 7)).toBe(false);
  });

  it("is false for an undrafted player", () => {
    expect(draftedHere(null, 7)).toBe(false);
  });
});

describe("ordinal", () => {
  it("spells the English suffixes, teens included", () => {
    expect(
      [1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111].map(ordinal),
    ).toEqual([
      "1st",
      "2nd",
      "3rd",
      "4th",
      "11th",
      "12th",
      "13th",
      "21st",
      "22nd",
      "23rd",
      "101st",
      "111th",
    ]);
  });
});

describe("auctionContext", () => {
  const index = indexDraftPicks(PICKS);
  const context = (id: string) => auctionContext(must(index, id), index.values());

  it("ranks by price overall and within the position, as competition ranks", () => {
    expect(context("a")).toEqual({
      overallRank: 1,
      pickCount: 5,
      position: "RB",
      positionRank: 1,
      positionCount: 3,
      positionAverage: 51,
    });
    // b and c share $61: both 2nd overall, and the next price is 4th.
    expect(context("b").overallRank).toBe(2);
    expect(context("c").overallRank).toBe(2);
    expect(context("d").overallRank).toBe(4);
  });

  it("ranks within the position only against that position", () => {
    expect(context("c")).toMatchObject({
      position: "WR",
      positionRank: 1,
      positionCount: 1,
      positionAverage: 61,
    });
    expect(context("d")).toMatchObject({ positionRank: 3, positionCount: 3 });
  });

  it("rounds the position average to the dollar", () => {
    expect(context("e").positionAverage).toBe(1);
    const skewed = indexDraftPicks([
      pick({ sleeper_player_id: "x", amount: 10 }),
      pick({ sleeper_player_id: "y", amount: 11 }),
      pick({ sleeper_player_id: "z", amount: 11 }),
    ]);
    expect(auctionContext(must(skewed, "x"), skewed.values()).positionAverage).toBe(
      11,
    );
  });

  it("has no position rank when the pick carries no position", () => {
    const bare = indexDraftPicks([
      pick({ sleeper_player_id: "n", amount: 5, position: null }),
    ]);
    expect(auctionContext(must(bare, "n"), bare.values())).toMatchObject({
      position: null,
      positionRank: null,
      positionCount: 0,
      positionAverage: null,
    });
  });
});

describe("auctionContextLine", () => {
  it("reads as the spec's example", () => {
    expect(
      auctionContextLine({
        overallRank: 9,
        pickCount: 162,
        position: "RB",
        positionRank: 4,
        positionCount: 40,
        positionAverage: 22,
      }),
    ).toBe("9th priciest pick · 4th RB · RB average $22");
  });

  it("stops after the overall rank when there is no position", () => {
    expect(
      auctionContextLine({
        overallRank: 150,
        pickCount: 162,
        position: null,
        positionRank: null,
        positionCount: 0,
        positionAverage: null,
      }),
    ).toBe("150th priciest pick");
  });
});
