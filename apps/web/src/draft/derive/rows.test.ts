/** @vitest-environment node */
import { describe, expect, it } from "vitest";

import {
  draftBudgetPerTeam,
  draftRows,
  draftSummary,
  parseDraftSortMode,
  sortDraftRows,
  teamSpend,
  type DraftRow,
} from "./rows";

const DRAFTED_AT = "2026-09-07T23:01:30Z";
const picks = [
  { team_id: 11, sleeper_player_id: "9493", pick_no: 1, round: 1, position: "WR", amount: 53, drafted_at: DRAFTED_AT },
  { team_id: 3, sleeper_player_id: "4046", pick_no: 2, round: 1, position: "QB", amount: 45, drafted_at: DRAFTED_AT },
  { team_id: 11, sleeper_player_id: "1111", pick_no: 3, round: 1, position: "RB", amount: 45, drafted_at: DRAFTED_AT },
  { team_id: 3, sleeper_player_id: "2222", pick_no: 4, round: 1, position: "K", amount: 1, drafted_at: DRAFTED_AT },
];
const teams = [
  { id: 11, sleeper_roster_id: 1, team_name: "Ray Regime", member_id: 101 },
  { id: 3, sleeper_roster_id: 2, team_name: "chobes", member_id: 103 },
];
const members = [
  { id: 101, sleeper_display_name: "jrayay", nickname: "Jesse" },
  { id: 103, sleeper_display_name: "chobes", nickname: null },
];
const players = [
  { sleeper_player_id: "9493", full_name: "Puka Nacua", position: "WR", team: "LAR", injury_status: null },
  { sleeper_player_id: "4046", full_name: "Patrick Mahomes", position: "QB", team: "KC", injury_status: null },
];

const rows = () => draftRows(picks, teams, members, players);

describe("draftRows", () => {
  it("joins a pick to its name, NFL team, and owner label", () => {
    const [first] = rows();
    expect(first).toEqual({
      sleeperPlayerId: "9493",
      pickNo: 1,
      round: 1,
      amount: 53,
      position: "WR",
      fullName: "Puka Nacua",
      nflTeam: "LAR",
      teamId: 11,
      ownerName: "Jesse",
    });
  });

  it("names a player the directory lacks by his id, and keeps the pick's position", () => {
    const row = rows().find((r) => r.sleeperPlayerId === "1111") as DraftRow;
    expect(row.fullName).toBe("Unknown player 1111");
    expect(row.position).toBe("RB");
    expect(row.nflTeam).toBeNull();
  });

  it("falls back to the Sleeper display name for an owner with no nickname", () => {
    expect(rows().find((r) => r.teamId === 3)?.ownerName).toBe("chobes");
  });
});

describe("sortDraftRows", () => {
  it("is pick order by default", () => {
    expect(sortDraftRows(rows(), "pick").map((r) => r.pickNo)).toEqual([1, 2, 3, 4]);
  });

  it("sorts by price, ties broken by pick order", () => {
    expect(sortDraftRows(rows(), "price").map((r) => r.pickNo)).toEqual([1, 2, 3, 4]);
    expect(sortDraftRows(rows(), "price").map((r) => r.amount)).toEqual([53, 45, 45, 1]);
  });

  it("groups by team in spend order, priciest first within a team, and never mutates its input", () => {
    const input = rows();
    const sorted = sortDraftRows(input, "team");
    expect(sorted.map((r) => `${r.teamId}:${r.amount}`)).toEqual(["11:53", "11:45", "3:45", "3:1"]);
    expect(input.map((r) => r.pickNo)).toEqual([1, 2, 3, 4]);
  });
});

describe("parseDraftSortMode", () => {
  it("reads the three modes and falls back to pick order", () => {
    expect(parseDraftSortMode("price")).toBe("price");
    expect(parseDraftSortMode("team")).toBe("team");
    expect(parseDraftSortMode("nonsense")).toBe("pick");
    expect(parseDraftSortMode(null)).toBe("pick");
  });
});

describe("teamSpend", () => {
  it("totals each team, in spend order, with the unspent dollars as FAAB", () => {
    expect(teamSpend(rows(), 200)).toEqual([
      { teamId: 11, ownerName: "Jesse", picks: 2, spent: 98, unspent: 102, faab: 510 },
      { teamId: 3, ownerName: "chobes", picks: 2, spent: 46, unspent: 154, faab: 770 },
    ]);
  });

  it("carries no unspent figure without a budget", () => {
    expect(teamSpend(rows(), null)[0]).toMatchObject({ spent: 98, unspent: null, faab: null });
  });
});

describe("draftBudgetPerTeam", () => {
  it("is the FAAB budget divided by the league's five-to-one rule", () => {
    expect(draftBudgetPerTeam(1000)).toBe(200);
    expect(draftBudgetPerTeam(null)).toBeNull();
  });
});

describe("draftSummary", () => {
  it("counts the picks, the dollars, and the average to the dollar", () => {
    expect(draftSummary(rows())).toEqual({ pickCount: 4, spent: 144, average: 36 });
    expect(draftSummary([])).toEqual({ pickCount: 0, spent: 0, average: null });
  });
});
