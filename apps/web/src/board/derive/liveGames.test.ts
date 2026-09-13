import { describe, expect, it } from "vitest";

import { parseLiveGames, scheduleWithLiveGames } from "./liveGames";

function slate(state = "in", period = 2, clock = 0) {
  return {
    season: { year: 2026, type: 2 },
    week: { number: 1 },
    events: [
      {
        season: { year: 2026, type: 2 },
        week: { number: 1 },
        status: { period, clock, type: { state, completed: state === "post" } },
        competitions: [
          {
            competitors: ["WSH", "JAC"].map((abbreviation) => ({
              team: { abbreviation },
            })),
          },
        ],
      },
    ],
  };
}

describe("live game clocks", () => {
  it.each([
    [1, 900, 1],
    [2, 0, 0.5],
    [3, 900, 0.5],
    [4, 360, 0.1],
    [4, 0, 0],
    [5, 600, 1 / 6],
  ])(
    "uses the game clock at period %s with %s seconds",
    (period, clock, fraction) => {
      const games = parseLiveGames(slate("in", period, clock), 2026, 1);
      expect(games.WAS).toEqual({
        status: "live",
        remainingFraction: fraction,
      });
      expect(games.JAX).toEqual(games.WAS);
    },
  );
  it("recognizes upcoming and finished games", () => {
    expect(parseLiveGames(slate("pre"), 2026, 1).WAS).toEqual({
      status: "remaining",
      remainingFraction: 1,
    });
    expect(parseLiveGames(slate("post"), 2026, 1).WAS).toEqual({
      status: "done",
      remainingFraction: 0,
    });
  });
  it("rejects another season, week, or postseason", () => {
    expect(() => parseLiveGames(slate(), 2025, 1)).toThrow();
    expect(() => parseLiveGames(slate(), 2026, 2)).toThrow();
    expect(() =>
      parseLiveGames({ ...slate(), season: { year: 2026, type: 3 } }, 2026, 1),
    ).toThrow();
    const data = slate();
    data.events[0].week.number = 2;
    expect(() => parseLiveGames(data, 2026, 1)).toThrow();
  });
  it.each([
    [0, 0],
    [2, -1],
    [3, NaN],
    [2.5, 10],
    [4, 901],
  ])("rejects invalid period %s / clock %s", (period, clock) => {
    expect(() => parseLiveGames(slate("in", period, clock), 2026, 1)).toThrow();
  });
  it("does not invent clocks for an unknown status", () => {
    expect(() => parseLiveGames(slate("suspended"), 2026, 1)).toThrow();
    expect(() => parseLiveGames({}, 2026, 1)).toThrow();
  });
  it("lets fresh finals override cached schedule states, retaining other games and byes", () => {
    expect(
      scheduleWithLiveGames(
        { WAS: "live", KC: "remaining", BUF: "bye" },
        parseLiveGames(slate("post"), 2026, 1),
      ),
    ).toEqual({ WAS: "done", JAX: "done", KC: "remaining", BUF: "bye" });
    expect(scheduleWithLiveGames(null, null)).toBeNull();
  });
});
