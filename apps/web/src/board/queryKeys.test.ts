/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import { boardKeys, fingerprintIds } from "./queryKeys";

describe("fingerprintIds", () => {
  it("is stable regardless of the order the ids arrive in", () => {
    expect(fingerprintIds(["9999", "4046"])).toBe(fingerprintIds(["4046", "9999"]));
  });

  it("changes when a player is added to the held set", () => {
    expect(fingerprintIds(["4046"])).not.toBe(fingerprintIds(["4046", "9999"]));
  });

  it("changes when a player is swapped for another", () => {
    expect(fingerprintIds(["4046"])).not.toBe(fingerprintIds(["9999"]));
  });

  it("has one fingerprint for the empty set", () => {
    expect(fingerprintIds([])).toBe(fingerprintIds([]));
  });
});

describe("boardKeys", () => {
  it("keys the player queries on the held ids, not just the season", () => {
    const before = boardKeys.players(1, fingerprintIds(["4046"]));
    const after = boardKeys.players(1, fingerprintIds(["4046", "9999"]));
    expect(before).not.toEqual(after);
  });

  it("keys player projections on the season, week and held ids", () => {
    const key = boardKeys.playerProjections(2026, 3, fingerprintIds(["4046"]));
    expect(key.slice(0, 4)).toEqual(["board", "player_projections", 2026, 3]);
    expect(key).toHaveLength(5);
  });

  it("keeps the roster_holdings branch separate from the players branch", () => {
    expect(boardKeys.rosterHoldings(1)).toEqual(["board", "roster_holdings", 1]);
    expect(boardKeys.players(1, "x")[1]).toBe("players");
  });

  it("nests every key under the all key so one invalidation covers the board", () => {
    const keys = [
      boardKeys.nflState(),
      boardKeys.season(2026),
      boardKeys.teams(1),
      boardKeys.members(),
      boardKeys.teamSeasonState(1),
      boardKeys.teamWeekProjections(1, 3),
      boardKeys.rosterHoldings(1),
      boardKeys.finalRosters(1),
      boardKeys.players(1, "x"),
      boardKeys.playerProjections(2026, 3, "x"),
      boardKeys.weeklyResults(1),
    ];
    for (const key of keys) {
      expect(key[0]).toBe(boardKeys.all[0]);
    }
  });
});
