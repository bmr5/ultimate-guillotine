import { describe, expect, it } from "vitest";

import { EMPTY_FILTERS } from "../types";
import { filterTrades } from "./filter";
import {
  mergeTradeSources,
  normalizeCatalogTrade,
  normalizeRegisteredTrade,
} from "./merge";

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
  announcement: "SENTINEL_CATALOG_ANNOUNCEMENT",
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
  // The one field of the terms document that is meant to reach the page, and its own sentinel
  // says so: `announcement` must be found, the two below must not.
  announcement: "SENTINEL_EVIDENCE_EXCERPT",
  // Distinct sentinels, so the drop of each field is proved on its own. `display_name` is the
  // bare Sleeper username the terms document carries; it must never reach the page, and a
  // sentinel that also happens to be a member's real `sleeper_display_name` would not prove it.
  parties: [
    { member_id: 1, display_name: "SENTINEL_PARTY_DISPLAY_NAME" },
    { member_id: 2 },
  ],
  assets: [
    {
      kind: "faab",
      amount: 12,
      from_member_id: 1,
      to_member_id: 2,
      player_id: null,
      player_name: null,
      unit: "faab",
      description: "SENTINEL_ASSET_DESCRIPTION",
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

  it("carries a catalog row's announcement onto the trade", () => {
    const { trades } = mergeTradeSources([CATALOG_2024], [], [], MEMBERS);
    expect(trades[0].announcement).toBe("SENTINEL_CATALOG_ANNOUNCEMENT");
  });

  it("leaves a catalog row with no announcement carrying none", () => {
    const { trades } = mergeTradeSources(
      [{ ...CATALOG_2024, announcement: null }],
      [],
      [],
      MEMBERS,
    );
    expect(trades[0].announcement).toBeNull();
  });

  // A column PostgREST did not return arrives as `undefined`, not as `null`, and the search box
  // folds this string on every keystroke — so the normalizer answers `null` for either.
  it("reads a missing announcement column as no announcement, never undefined", () => {
    const withoutColumn: Record<string, unknown> = { ...CATALOG_2024 };
    delete withoutColumn.announcement;
    const { trades } = mergeTradeSources(
      [withoutColumn as unknown as typeof CATALOG_2024],
      [],
      [],
      MEMBERS,
    );
    expect(trades[0].announcement).toBeNull();
    expect(
      filterTrades(trades, { ...EMPTY_FILTERS, search: "announcement" }),
    ).toEqual([]);
  });

  it("labels owners by nickname, else Sleeper display name", () => {
    const { trades } = mergeTradeSources([CATALOG_2024], [], [], MEMBERS);
    expect(trades[0].parties.map((party) => party.label)).toEqual([
      "Alpha",
      "Bravo Display",
    ]);
  });

  // Ben's ruling: the catalog's old nicknames are not going to be mapped one by one, and a
  // party the directory does not carry is a manager who has left. The party keeps its place —
  // dropping it would make the row read as a smaller trade than it was.
  it("labels a party the directory does not carry as a former manager", () => {
    const { trades } = mergeTradeSources(
      [{ ...CATALOG_2024, party_member_ids: [1, 99] }],
      [],
      [],
      MEMBERS,
    );
    expect(trades[0].parties.map((party) => party.label)).toEqual([
      "Alpha",
      "Former manager",
    ]);
    // And says which of the two is a name. The card counts the parties it cannot name into one
    // segment of the title, and it reads this flag rather than the stand-in label — a manager
    // whose nickname happened to be "Former manager" would otherwise fold in with them.
    expect(trades[0].parties.map((party) => party.resolved)).toEqual([
      true,
      false,
    ]);
    expect(trades[0].partyCount).toBe(2);
  });
});

describe("normalizeRegisteredTrade", () => {
  // Ben's ruling of 2026-09-10 moved exactly one field across this line, so this test now has
  // to prove a boundary rather than a blanket: the excerpt the league announced the trade in is
  // carried, and the Sleeper username and the chat's own phrasing of the assets still are not.
  // Three sentinels, one expected to be found and two expected to be missing — a single
  // "no free text" sentinel could no longer tell those apart.
  it("carries the announcement out of the terms document and nothing else", () => {
    const trade = normalizeRegisteredTrade(REGISTERED, REVISION, MEMBERS);
    const serialized = JSON.stringify(trade);
    expect(trade.announcement).toBe("SENTINEL_EVIDENCE_EXCERPT");
    expect(serialized).not.toContain("SENTINEL_PARTY_DISPLAY_NAME");
    expect(serialized).not.toContain("SENTINEL_ASSET_DESCRIPTION");
    expect(trade.faabTotal).toBe(12);
    expect(trade.week).toBe(4);
    expect(trade.sourceLabel).toBe("T-2025-014");
  });

  it("has no announcement when the trade has no current revision", () => {
    const trade = normalizeRegisteredTrade(REGISTERED, undefined, MEMBERS);
    expect(trade.announcement).toBeNull();
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
            player_name: "SENTINEL_ASSET_PLAYER_NAME from week 3",
            from_member_id: 1,
            to_member_id: 2,
          },
        ],
      },
      MEMBERS,
    );
    expect(JSON.stringify(trade)).not.toContain("SENTINEL_ASSET_PLAYER_NAME");
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

  it("skips a null or primitive party and a null or primitive asset", () => {
    const trade = normalizeRegisteredTrade(
      REGISTERED,
      {
        ...REVISION,
        parties: [null, { member_id: 1 }, "party two", { member_id: 2 }],
        assets: [
          null,
          "a bare string",
          { kind: "faab", amount: 4, from_member_id: 1, to_member_id: 2 },
        ],
      },
      MEMBERS,
    );
    expect(trade.parties.map((party) => party.memberId)).toEqual([1, 2]);
    // The two unusable entries are gone, not counted as unresolved parties.
    expect(trade.partyCount).toBe(2);
    expect(trade.unresolvedParties).toBe(0);
    expect(trade.assets).toEqual([
      { kind: "faab", amount: 4, fromParty: 0, toParty: 1 },
    ]);
  });

  it("reports an unresolved counterparty as no side at all, never -1", () => {
    const trade = normalizeRegisteredTrade(
      REGISTERED,
      {
        ...REVISION,
        assets: [
          {
            kind: "faab",
            amount: 7,
            from_member_id: 1,
            to_member_id: 99,
          },
          {
            kind: "player",
            player_id: "4034",
            from_member_id: 99,
            to_member_id: 2,
          },
        ],
      },
      MEMBERS,
    );
    expect(trade.assets).toEqual([
      { kind: "faab", amount: 7, fromParty: 0, toParty: null },
      {
        kind: "player",
        playerId: "4034",
        name: "",
        position: null,
        fromParty: null,
        toParty: 1,
      },
    ]);
  });
});

describe("normalizeCatalogTrade", () => {
  it("skips a null or primitive asset instead of throwing", () => {
    const trade = normalizeCatalogTrade(
      {
        ...CATALOG_2024,
        assets: [null, "a bare string", 7, ...CATALOG_2024.assets],
      },
      MEMBERS,
    );
    expect(trade.assets).toEqual([
      { kind: "faab", amount: 5, fromParty: 0, toParty: 1 },
    ]);
  });

  it("takes a non-string player name as no name, and stays searchable", () => {
    const trade = normalizeCatalogTrade(
      {
        ...CATALOG_2024,
        assets: [
          {
            kind: "player",
            sleeper_player_id: 4034,
            name: 123,
            position: 7,
            from_party: "0",
            to_party: 1.5,
          },
        ],
      },
      MEMBERS,
    );
    expect(trade.assets).toEqual([
      {
        kind: "player",
        playerId: null,
        name: "",
        position: null,
        fromParty: null,
        toParty: null,
      },
    ]);
    expect(() =>
      filterTrades([trade], { ...EMPTY_FILTERS, search: "nacua" }),
    ).not.toThrow();
    expect(
      filterTrades([trade], { ...EMPTY_FILTERS, search: "nacua" }),
    ).toEqual([]);
  });
});
