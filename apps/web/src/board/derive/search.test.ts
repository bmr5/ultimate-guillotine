/**
 * The matcher is string comparison over plain data, so it runs under node like the other derive
 * modules.
 *
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { BoardTeam, RosterPlayer } from "../types";
import { filterTeams, matchTeam, normalizeSearchText } from "./search";

const player = (id: string, fullName: string): RosterPlayer => ({
  sleeperPlayerId: id,
  fullName,
  position: "RB",
  nflTeam: "SF",
  slot: "starter",
  slotIndex: 0,
  lineupPosition: "RB",
  projectedPoints: 12,
});

const team = (over: Partial<BoardTeam> & { teamId: number }): BoardTeam => ({
  isRosterFrozen: false,
  teamName: "The Choppers",
  ownerName: "benray",
  sleeperRosterId: over.teamId,
  projectedPoints: 100,
  coveragePct: 100,
  isProvisional: false,
  projectionComputedAt: null,
  faabRemaining: 50,
  wins: 0,
  losses: 0,
  ties: 0,
  pointsFor: 100,
  isEliminated: false,
  eliminatedWeek: null,
  eliminationSource: null,
  roster: [player("1", "Christian McCaffrey")],
  ...over,
});

describe("normalizeSearchText", () => {
  it("folds case and strips combining marks", () => {
    expect(normalizeSearchText("Puka Nacuá")).toBe("puka nacua");
    expect(normalizeSearchText("JOSÉ")).toBe("jose");
  });
});

describe("matchTeam", () => {
  it("matches everything on an empty term", () => {
    expect(matchTeam(team({ teamId: 1 }), "   ")).toEqual({
      matches: true,
      matchedPlayerIds: [],
    });
  });

  it("matches on owner display name, case-insensitively", () => {
    expect(matchTeam(team({ teamId: 1 }), "BENR").matches).toBe(true);
  });

  it("matches on team name and reports no players", () => {
    expect(matchTeam(team({ teamId: 1 }), "chopper")).toEqual({
      matches: true,
      matchedPlayerIds: [],
    });
  });

  it("matches on player name and reports the matched player", () => {
    const result = matchTeam(team({ teamId: 1 }), "mccaffrey");
    expect(result.matches).toBe(true);
    expect(result.matchedPlayerIds).toEqual(["1"]);
  });

  it("still reports the matched players when the team name matches too", () => {
    const result = matchTeam(
      team({
        teamId: 1,
        teamName: "Chopper Nation",
        roster: [player("7", "Chopper Jones"), player("8", "Puka Nacua")],
      }),
      "chopper",
    );
    expect(result).toEqual({ matches: true, matchedPlayerIds: ["7"] });
  });

  it("ignores accents in the term and in the data", () => {
    const accented = team({
      teamId: 1,
      ownerName: "José Ramírez",
      roster: [player("5", "Puka Nacuá")],
    });
    expect(matchTeam(accented, "nacua").matchedPlayerIds).toEqual(["5"]);
    expect(matchTeam(accented, "jose ramirez").matches).toBe(true);
    expect(
      matchTeam(
        team({ teamId: 1, roster: [player("5", "Puka Nacua")] }),
        "nacuá",
      ).matchedPlayerIds,
    ).toEqual(["5"]);
  });

  it("does not match unrelated text", () => {
    expect(matchTeam(team({ teamId: 1 }), "zzzz")).toEqual({
      matches: false,
      matchedPlayerIds: [],
    });
  });
});

describe("filterTeams", () => {
  it("keeps only matching teams and auto-expands player matches", () => {
    const teams = [
      team({ teamId: 1 }),
      team({
        teamId: 2,
        ownerName: "charlie",
        teamName: "Gulag Bound",
        roster: [player("9", "Puka Nacua")],
      }),
    ];
    const result = filterTeams(teams, "puka");
    expect(result.teams.map((t) => t.teamId)).toEqual([2]);
    expect(result.autoExpandTeamIds).toEqual([2]);
    expect([...result.matchedPlayerIds]).toEqual(["9"]);
  });

  it("auto-expands only the teams a player matched, not the ones matched by name", () => {
    const teams = [
      team({ teamId: 1, teamName: "Chopper Nation" }),
      team({
        teamId: 2,
        ownerName: "charlie",
        teamName: "Gulag Bound",
        roster: [player("9", "Chopper Jones")],
      }),
    ];
    const result = filterTeams(teams, "chopper");
    expect(result.teams.map((t) => t.teamId)).toEqual([1, 2]);
    expect(result.autoExpandTeamIds).toEqual([2]);
    expect([...result.matchedPlayerIds]).toEqual(["9"]);
  });

  it("returns every team for an empty term", () => {
    const teams = [team({ teamId: 1 }), team({ teamId: 2 })];
    expect(filterTeams(teams, "").teams).toHaveLength(2);
  });

  it("keeps the incoming team order and matches no one on a miss", () => {
    const result = filterTeams(
      [team({ teamId: 1 }), team({ teamId: 2 })],
      "zzzz",
    );
    expect(result.teams).toEqual([]);
    expect(result.autoExpandTeamIds).toEqual([]);
    expect(result.matchedPlayerIds.size).toBe(0);
  });
});
