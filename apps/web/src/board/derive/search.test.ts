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

  it("drops the periods and apostrophes nobody types into a search box", () => {
    expect(normalizeSearchText("Ja'Marr Chase")).toBe("jamarr chase");
    expect(normalizeSearchText("T.J. Hockenson")).toBe("tj hockenson");
    expect(normalizeSearchText("Amon-Ra St. Brown")).toBe("amon-ra st brown");
  });

  it("folds a smart apostrophe to the straight one before dropping it", () => {
    expect(normalizeSearchText("Ja\u2019Marr")).toBe(
      normalizeSearchText("Ja'Marr"),
    );
  });

  it("collapses whitespace runs and trims the edges", () => {
    expect(normalizeSearchText("  puka   nacua ")).toBe("puka nacua");
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

  it("ignores the punctuation in a player's name", () => {
    const chase = team({ teamId: 1, roster: [player("2", "Ja'Marr Chase")] });
    expect(matchTeam(chase, "jamarr").matchedPlayerIds).toEqual(["2"]);

    const hockenson = team({
      teamId: 1,
      roster: [player("3", "T.J. Hockenson")],
    });
    expect(matchTeam(hockenson, "tj").matchedPlayerIds).toEqual(["3"]);

    const stBrown = team({
      teamId: 1,
      roster: [player("4", "Amon-Ra St. Brown")],
    });
    expect(matchTeam(stBrown, "st brown").matchedPlayerIds).toEqual(["4"]);
  });

  it("matches straight-quoted data from a term typed with a smart apostrophe", () => {
    const chase = team({ teamId: 1, roster: [player("2", "Ja'Marr Chase")] });
    expect(matchTeam(chase, "Ja\u2019Marr").matchedPlayerIds).toEqual(["2"]);
  });

  it("matches every word of the term in any order", () => {
    const nacua = team({ teamId: 1, roster: [player("9", "Puka Nacua")] });
    const result = matchTeam(nacua, "nacua puka");
    expect(result).toEqual({ matches: true, matchedPlayerIds: ["9"] });
  });

  it("ignores a double space between the words of a term", () => {
    const nacua = team({ teamId: 1, roster: [player("9", "Puka Nacua")] });
    expect(matchTeam(nacua, "puka  nacua").matchedPlayerIds).toEqual(["9"]);
  });

  it("misses when only some of the words land", () => {
    const nacua = team({ teamId: 1, roster: [player("9", "Puka Nacua")] });
    expect(matchTeam(nacua, "puka zzzz")).toEqual({
      matches: false,
      matchedPlayerIds: [],
    });
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

  it("matches no one on a total miss", () => {
    const result = filterTeams(
      [team({ teamId: 1 }), team({ teamId: 2 })],
      "zzzz",
    );
    expect(result.teams).toEqual([]);
    expect(result.autoExpandTeamIds).toEqual([]);
    expect(result.matchedPlayerIds.size).toBe(0);
  });
});
