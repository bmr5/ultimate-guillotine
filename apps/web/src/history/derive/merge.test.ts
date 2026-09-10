import { describe, expect, it } from "vitest";

import { mergeTradeSources, normalizeRegisteredTrade } from "./merge";

const MEMBERS = [
  { id: 1, nickname: "Alpha", sleeper_display_name: "alpha-user" },
  { id: 2, nickname: null, sleeper_display_name: "Bravo Display" },
];

const CATALOG_2024 = {
  id: 10,
  catalog_id: "2024-001",
  season: 2024,
  week: 3,
  occurred_on: null,
  trade_type: "trade",
  structure: "1-for-1",
  party_member_ids: [1, 2],
  party_count: 2,
  assets: [{ kind: "faab", amount: 5, from_party: 0, to_party: 1 }],
  faab_total: 5,
  confidence: "high" as const,
  source: "catalog" as const,
  unresolved_parties: 0,
  loaded_at: "2026-09-09T12:00:00Z",
};
const CATALOG_2025 = {
  ...CATALOG_2024,
  id: 11,
  catalog_id: "2025-001",
  season: 2025,
};

const REGISTERED = {
  id: 5,
  trade_code: "T-2025-014",
  status: "accepted" as const,
  current_revision_id: 50,
  seasons: { year: 2025 },
};
const REVISION = {
  id: 50,
  trade_id: 5,
  effective_week: 4,
  kind: "rental",
  parties: [{ member_id: 1, display_name: "alpha-user" }, { member_id: 2 }],
  assets: [
    {
      kind: "faab",
      amount: 12,
      from_member_id: 1,
      to_member_id: 2,
      player_id: null,
      player_name: null,
      unit: "faab",
      description: "SENTINEL PROSE",
    },
  ],
};

describe("mergeTradeSources", () => {
  it("drops catalog rows for a season the backfill has registered, and counts them", () => {
    const { trades, replacedByBackfill } = mergeTradeSources(
      [CATALOG_2024, CATALOG_2025],
      [REGISTERED],
      [REVISION],
      MEMBERS,
    );
    const seasons = trades.map(
      (trade) => `${trade.season}:${trade.sourceLabel}`,
    );
    expect(seasons).toEqual(["2025:T-2025-014", "2024:catalog"]);
    expect(replacedByBackfill).toBe(1);
  });

  it("keeps catalog rows for a season with no registered trades", () => {
    const { trades, replacedByBackfill } = mergeTradeSources(
      [CATALOG_2024],
      [],
      [],
      MEMBERS,
    );
    expect(trades).toHaveLength(1);
    expect(replacedByBackfill).toBe(0);
  });

  it("labels owners by nickname, else Sleeper display name", () => {
    const { trades } = mergeTradeSources([CATALOG_2024], [], [], MEMBERS);
    expect(trades[0].parties.map((party) => party.label)).toEqual([
      "Alpha",
      "Bravo Display",
    ]);
  });
});

describe("normalizeRegisteredTrade", () => {
  it("carries no free text out of the terms document", () => {
    const trade = normalizeRegisteredTrade(REGISTERED, REVISION, MEMBERS);
    expect(JSON.stringify(trade)).not.toContain("SENTINEL");
    expect(JSON.stringify(trade)).not.toContain("alpha-user");
    expect(trade.faabTotal).toBe(12);
    expect(trade.week).toBe(4);
    expect(trade.sourceLabel).toBe("T-2025-014");
  });

  it("marks a rescinded trade", () => {
    const trade = normalizeRegisteredTrade(
      { ...REGISTERED, status: "rescinded" },
      REVISION,
      MEMBERS,
    );
    expect(trade.rescinded).toBe(true);
  });

  it("carries no player name out of the terms document either", () => {
    const trade = normalizeRegisteredTrade(
      REGISTERED,
      {
        ...REVISION,
        assets: [
          {
            kind: "player",
            player_id: "4034",
            player_name: "SENTINEL the guy from week 3",
            from_member_id: 1,
            to_member_id: 2,
          },
        ],
      },
      MEMBERS,
    );
    expect(JSON.stringify(trade)).not.toContain("SENTINEL");
    expect(trade.assets).toEqual([
      {
        kind: "player",
        playerId: "4034",
        name: "",
        position: null,
        fromParty: 0,
        toParty: 1,
      },
    ]);
  });
});
