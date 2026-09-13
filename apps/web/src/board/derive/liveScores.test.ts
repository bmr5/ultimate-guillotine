import { describe, expect, it } from "vitest";

import { mergeLiveScores, parseLiveScores } from "./liveScores";

const matchup = {
  roster_id: 1,
  points: 20,
  custom_points: null,
  players_points: { qb: 22, def: -2, rb: 0 },
  starters: ["qb", "def", "rb", "0"],
};
const teams = [
  { id: 11, sleeper_roster_id: 1 },
  { id: 12, sleeper_roster_id: 2 },
];
const saved = [
  {
    season_id: 7,
    week: 3,
    team_id: 11,
    points: 10,
    players_points: { qb: 10 },
    starters: ["qb"],
    synced_at: "2026-09-13T18:00:00Z",
  },
];
const feed = {
  rows: parseLiveScores([matchup]),
  receivedAt: "2026-09-13T18:00:15Z",
};

describe("live Sleeper scores", () => {
  it("preserves zero and negative player scores and empty starter slots", () => {
    expect(feed.rows[0]).toEqual({
      rosterId: 1,
      points: 20,
      playersPoints: { qb: 22, def: -2, rb: 0 },
      starters: ["qb", "def", "rb", "0"],
    });
  });
  it("honors commissioner overrides, including zero", () => {
    expect(parseLiveScores([{ ...matchup, custom_points: 0 }])[0].points).toBe(
      0,
    );
    expect(parseLiveScores([{ ...matchup, custom_points: 25 }])[0].points).toBe(
      25,
    );
  });
  it.each([
    null,
    [],
    [null],
    [{ ...matchup, points: NaN }],
    [{ ...matchup, starters: null }],
    [{ ...matchup, players_points: [] }],
  ])("rejects incomplete feeds %#", (payload) => {
    expect(() => parseLiveScores(payload)).toThrow();
  });
  it("maps roster ids to DB teams without mixing other teams", () => {
    expect(mergeLiveScores(saved, feed, teams, 7, 3)[0]).toEqual({
      season_id: 7,
      week: 3,
      team_id: 11,
      points: 20,
      players_points: matchup.players_points,
      starters: matchup.starters,
      synced_at: feed.receivedAt,
    });
    expect(mergeLiveScores(saved, feed, [], 7, 3)).toEqual(saved);
  });
  it("keeps saved rows when no feed is available or when the DB is newer", () => {
    expect(mergeLiveScores(saved, undefined, teams, 7, 3)).toBe(saved);
    expect(
      mergeLiveScores(
        saved,
        { ...feed, receivedAt: "2026-09-13T17:59:00Z" },
        teams,
        7,
        3,
      ),
    ).toEqual(saved);
    const secondTeam = { ...saved[0], team_id: 12 };
    expect(
      mergeLiveScores([...saved, secondTeam], feed, teams, 7, 3),
    ).toContainEqual(secondTeam);
  });
});
