/** @vitest-environment node */
import { describe, expect, it } from "vitest";

import type { CatalogTrade } from "@/history/types";

import type { TransactionMoveRow, TransactionRow } from "../fetchers";
import { buildJourney, MATCH_WINDOW_MS, type JourneyInput } from "./journey";

const ME = "9493";
const PICK = {
  teamId: 1,
  amount: 53,
  pickNo: 1,
  round: 1,
  position: "WR",
  draftedAt: "2026-09-07T23:01:30.433Z",
};

const tx = (
  over: Partial<TransactionRow> & { id: number; kind: TransactionRow["kind"] },
): TransactionRow => ({
  week: 1,
  occurred_at: "2026-09-08T14:01:40Z",
  team_ids: [1, 16],
  faab_moves: [],
  waiver_bid: null,
  ...over,
});

const move = (
  transaction_id: number,
  sleeper_player_id: string,
  team_id: number,
  action: TransactionMoveRow["action"],
): TransactionMoveRow => ({ transaction_id, sleeper_player_id, team_id, action });

const registered = (
  over: Partial<CatalogTrade> & { key: string },
): CatalogTrade => ({
  season: 2026,
  week: 1,
  occurredOn: null,
  tradeType: "trade",
  structure: "2-team",
  parties: [
    { memberId: 101, label: "Ben", resolved: true },
    { memberId: 116, label: "Ryland", resolved: true },
  ],
  partyCount: 2,
  assets: [
    {
      kind: "player",
      playerId: ME,
      name: "Puka Nacua",
      position: "WR",
      fromParty: 0,
      toParty: 1,
    },
  ],
  confidence: "high",
  announcement: "Puka for Bowers plus 65",
  registeredAt: "2026-09-08T13:30:00Z",
  announcedBy: "Ben",
  sourceLabel: "T-2026-003",
  registered: true,
  rescinded: false,
  unresolvedParties: 0,
  ...over,
});

const input = (over: Partial<JourneyInput> = {}): JourneyInput => ({
  sleeperPlayerId: ME,
  season: 2026,
  pick: PICK,
  transactions: [],
  moves: [],
  registered: [],
  memberIdByTeamId: new Map([
    [1, 101],
    [16, 116],
    [8, 108],
  ]),
  ...over,
});

describe("buildJourney", () => {
  it("starts with the draft, dated by the auction", () => {
    expect(buildJourney(input())).toEqual([
      {
        kind: "drafted",
        key: "draft",
        at: PICK.draftedAt,
        week: null,
        teamId: 1,
        amount: 53,
        pickNo: 1,
      },
    ]);
  });

  it("has no draft entry for an undrafted pickup", () => {
    expect(buildJourney(input({ pick: null }))).toEqual([]);
  });

  it("reads a trade as from one team to another, with the other players and the FAAB", () => {
    const trade = tx({
      id: 5,
      kind: "trade",
      faab_moves: [{ amount: 65, from_team_id: 1, to_team_id: 16 }],
    });
    const moves = [
      move(5, ME, 16, "add"),
      move(5, ME, 1, "drop"),
      move(5, "12534", 1, "add"),
      move(5, "12534", 16, "drop"),
    ];
    const [, entry] = buildJourney(input({ transactions: [trade], moves }));
    expect(entry).toEqual({
      kind: "traded",
      key: "tx:5",
      at: "2026-09-08T14:01:40Z",
      week: 1,
      fromTeamId: 1,
      toTeamId: 16,
      others: [{ sleeperPlayerId: "12534", fromTeamId: 16, toTeamId: 1 }],
      faab: [{ amount: 65, fromTeamId: 1, toTeamId: 16 }],
      registered: null,
    });
  });

  it("reads a claim with its bid, a drop, and a commissioner move", () => {
    const transactions = [
      tx({
        id: 1,
        kind: "free_agent",
        week: 2,
        occurred_at: "2026-09-15T00:00:00Z",
        team_ids: [8],
      }),
      tx({
        id: 2,
        kind: "waiver",
        week: 3,
        occurred_at: "2026-09-23T00:00:00Z",
        team_ids: [16],
        waiver_bid: 12,
      }),
      tx({
        id: 3,
        kind: "waiver",
        week: 3,
        occurred_at: "2026-09-23T01:00:00Z",
        team_ids: [8],
      }),
      tx({
        id: 4,
        kind: "commissioner",
        week: 4,
        occurred_at: "2026-09-30T00:00:00Z",
        team_ids: [1],
      }),
    ];
    const moves = [
      move(1, ME, 8, "drop"),
      move(2, ME, 16, "add"),
      move(3, ME, 8, "drop"),
      move(3, "0000", 8, "add"),
      move(4, ME, 1, "add"),
    ];
    const entries = buildJourney(input({ pick: null, transactions, moves }));
    expect(entries.map((e) => e.kind)).toEqual([
      "dropped",
      "claimed",
      "dropped",
      "commissioner",
    ]);
    expect(entries[0]).toMatchObject({ teamId: 8, week: 2 });
    expect(entries[1]).toMatchObject({ teamId: 16, bid: 12 });
    expect(entries[3]).toMatchObject({ teamId: 1, action: "add" });
  });

  it("reads a free-agent add as added", () => {
    const pickup = tx({ id: 9, kind: "free_agent", team_ids: [8] });
    const entries = buildJourney(
      input({ pick: null, transactions: [pickup], moves: [move(9, ME, 8, "add")] }),
    );
    expect(entries).toEqual([
      { kind: "added", key: "tx:9", at: "2026-09-08T14:01:40Z", week: 1, teamId: 8 },
    ]);
  });

  it("orders entries by time, the draft first", () => {
    const later = tx({
      id: 2,
      kind: "free_agent",
      week: 3,
      occurred_at: "2026-09-23T00:00:00Z",
      team_ids: [8],
    });
    const earlier = tx({
      id: 1,
      kind: "free_agent",
      week: 2,
      occurred_at: "2026-09-15T00:00:00Z",
      team_ids: [8],
    });
    const entries = buildJourney(
      input({
        transactions: [later, earlier],
        moves: [move(2, ME, 8, "add"), move(1, ME, 8, "drop")],
      }),
    );
    expect(entries.map((e) => e.key)).toEqual(["draft", "tx:1", "tx:2"]);
  });

  describe("matching a registered trade", () => {
    const trade = tx({ id: 5, kind: "trade" });
    const moves = [move(5, ME, 16, "add"), move(5, ME, 1, "drop")];

    it("attaches the registered trade with the same owners announced within the window", () => {
      const entries = buildJourney(
        input({ transactions: [trade], moves, registered: [registered({ key: "r1" })] }),
      );
      expect(entries[1]).toMatchObject({
        kind: "traded",
        registered: {
          key: "r1",
          tradeCode: "T-2026-003",
          announcement: "Puka for Bowers plus 65",
          rescinded: false,
        },
      });
      // Matched, so not also an "announced" entry.
      expect(entries).toHaveLength(2);
    });

    it("prefers the nearest announcement when two qualify, and links each once", () => {
      const near = registered({
        key: "near",
        registeredAt: "2026-09-08T14:30:00Z",
        sourceLabel: "T-NEAR",
      });
      const far = registered({
        key: "far",
        registeredAt: "2026-09-08T02:00:00Z",
        sourceLabel: "T-FAR",
      });
      const entries = buildJourney(
        input({ transactions: [trade], moves, registered: [far, near] }),
      );
      // The unmatched announcement sorts by its own time, so the trade is found by kind.
      expect(entries.find((e) => e.kind === "traded")).toMatchObject({
        registered: { tradeCode: "T-NEAR" },
      });
      expect(entries.find((e) => e.kind === "announced")).toMatchObject({
        registered: { tradeCode: "T-FAR" },
      });
    });

    it("does not match outside the window, a different owner set, an unresolved party, or another season", () => {
      const late = registered({
        key: "late",
        registeredAt: new Date(
          Date.parse("2026-09-08T14:01:40Z") + MATCH_WINDOW_MS + 1000,
        ).toISOString(),
      });
      const otherOwners = registered({
        key: "owners",
        parties: [
          { memberId: 101, label: "Ben", resolved: true },
          { memberId: 108, label: "Nick", resolved: true },
        ],
      });
      const unresolved = registered({
        key: "unresolved",
        parties: [
          { memberId: 101, label: "Ben", resolved: true },
          { memberId: 999, label: "Former manager", resolved: false },
        ],
      });
      const lastYear = registered({ key: "2025", season: 2025 });
      const entries = buildJourney(
        input({
          transactions: [trade],
          moves,
          registered: [late, otherOwners, unresolved, lastYear],
        }),
      );
      expect(entries.find((e) => e.kind === "traded")).toMatchObject({
        registered: null,
      });
      expect(
        entries.filter((e) => e.kind === "announced").map((e) => e.key),
      ).toEqual(expect.arrayContaining(["reg:late", "reg:owners", "reg:unresolved"]));
      expect(entries.some((e) => e.key === "reg:2025")).toBe(false);
    });

    it("keeps a registered trade with no Sleeper counterpart as an announced entry", () => {
      const entries = buildJourney(input({ registered: [registered({ key: "r1" })] }));
      expect(entries[1]).toEqual({
        kind: "announced",
        key: "reg:r1",
        at: "2026-09-08T13:30:00Z",
        week: 1,
        registered: {
          key: "r1",
          tradeCode: "T-2026-003",
          announcement: "Puka for Bowers plus 65",
          rescinded: false,
        },
      });
    });

    it("ignores a registered trade that does not name this player", () => {
      const other = registered({
        key: "other",
        assets: [
          {
            kind: "player",
            playerId: "0000",
            name: "Someone",
            position: null,
            fromParty: 0,
            toParty: 1,
          },
        ],
      });
      expect(buildJourney(input({ registered: [other] }))).toHaveLength(1);
    });
  });
});
