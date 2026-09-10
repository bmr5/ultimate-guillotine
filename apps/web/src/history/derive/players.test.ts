/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { HistoryPlayerRow } from "../fetchers";
import type { CatalogTrade } from "../types";
import { resolvePlayerNames, UNLISTED_PLAYER_LABEL } from "./players";

const PLAYERS: HistoryPlayerRow[] = [
  { sleeper_player_id: "4034", full_name: "Alvin Kamara", position: "RB" },
  { sleeper_player_id: "6794", full_name: "Justin Jefferson", position: "WR" },
];

function tradeWith(assets: CatalogTrade["assets"]): CatalogTrade {
  return {
    key: "registered:1",
    season: 2025,
    week: 3,
    occurredOn: null,
    tradeType: "trade",
    structure: "2-team",
    parties: [],
    partyCount: 2,
    assets,
    faabTotal: null,
    confidence: "high",
    sourceLabel: "T-2025-014",
    registered: true,
    rescinded: false,
    unresolvedParties: 0,
  };
}

describe("resolvePlayerNames", () => {
  it("names a registered player asset from the player directory", () => {
    const [trade] = resolvePlayerNames(
      [
        tradeWith([
          {
            kind: "player",
            playerId: "4034",
            name: "",
            position: null,
            fromParty: 0,
            toParty: 1,
          },
        ]),
      ],
      PLAYERS,
    );
    expect(trade.assets[0]).toEqual({
      kind: "player",
      playerId: "4034",
      name: "Alvin Kamara",
      position: "RB",
      fromParty: 0,
      toParty: 1,
    });
  });

  it("labels an id the directory does not carry, and one with no id at all", () => {
    const [trade] = resolvePlayerNames(
      [
        tradeWith([
          {
            kind: "player",
            playerId: "99999",
            name: "",
            position: null,
            fromParty: 0,
            toParty: 1,
          },
          {
            kind: "player",
            playerId: null,
            name: "",
            position: null,
            fromParty: 1,
            toParty: 0,
          },
        ]),
      ],
      PLAYERS,
    );
    expect(trade.assets[0]).toMatchObject({
      name: UNLISTED_PLAYER_LABEL,
      position: null,
    });
    expect(trade.assets[1]).toMatchObject({
      name: UNLISTED_PLAYER_LABEL,
      position: null,
    });
  });

  it("leaves a catalog asset that already has a name alone", () => {
    // The catalog's own name is what an analyst curated for display; the directory must not
    // overwrite it, and a directory row for the same id must not change its position either.
    const named = {
      kind: "player" as const,
      playerId: "4034",
      name: "A. Kamara",
      position: "WR",
      fromParty: 0,
      toParty: 1,
    };
    const input = [tradeWith([named])];
    const [trade] = resolvePlayerNames(input, PLAYERS);
    expect(trade.assets[0]).toEqual(named);
    // Nothing changed, so nothing is copied: the trade keeps its identity and the memoised
    // consumers downstream do not re-render.
    expect(trade).toBe(input[0]);
  });

  it("leaves faab and condition assets untouched", () => {
    const [trade] = resolvePlayerNames(
      [
        tradeWith([
          { kind: "faab", amount: 12, fromParty: 0, toParty: 1 },
          { kind: "condition", label: "rental" },
        ]),
      ],
      PLAYERS,
    );
    expect(trade.assets).toEqual([
      { kind: "faab", amount: 12, fromParty: 0, toParty: 1 },
      { kind: "condition", label: "rental" },
    ]);
  });

  it("labels every player asset when the directory has not loaded yet", () => {
    const [trade] = resolvePlayerNames(
      [
        tradeWith([
          {
            kind: "player",
            playerId: "4034",
            name: "",
            position: null,
            fromParty: 0,
            toParty: 1,
          },
        ]),
      ],
      [],
    );
    expect(trade.assets[0]).toMatchObject({ name: UNLISTED_PLAYER_LABEL });
  });
});
