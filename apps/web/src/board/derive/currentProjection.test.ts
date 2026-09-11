import { describe, expect, it } from "vitest";

import { currentProjection, parseWeekSchedule } from "./currentProjection";

const brown = {
  sleeperPlayerId: "5859",
  slot: "starter" as const,
  nflTeam: "PHI",
  projectedPoints: 16.86,
  livePoints: 5.6,
  injuryStatus: null,
};
const rest = {
  ...brown,
  sleeperPlayerId: "rest",
  nflTeam: "KC",
  projectedPoints: 95.11,
  livePoints: 0,
};

describe("current projection", () => {
  it("replaces Brown's full-game estimate with his actual score", () => {
    expect(
      currentProjection([brown, rest], 5.6, { PHI: "done", KC: "remaining" }),
    ).toBe(100.71);
    expect(brown.projectedPoints + rest.projectedPoints).toBeCloseTo(111.97);
  });
  it("matches the original before kickoff", () => {
    expect(
      currentProjection([{ ...brown, livePoints: 0 }, rest], 0, {
        PHI: "remaining",
        KC: "remaining",
      }),
    ).toBe(111.97);
  });
  it.each([0, -2, 25])("counts finished actual points of %s", (points) => {
    expect(
      currentProjection([{ ...brown, livePoints: points }, rest], points, {
        PHI: "done",
        KC: "remaining",
      }),
    ).toBe(Math.round((95.11 + points) * 100) / 100);
  });
  it("preserves a commissioner score adjustment", () => {
    expect(
      currentProjection([brown, rest], 7.6, { PHI: "done", KC: "remaining" }),
    ).toBe(102.71);
  });
  it("equals the actual team score after every game, even without projections", () => {
    expect(
      currentProjection([{ ...brown, projectedPoints: null }], 5.6, {
        PHI: "done",
      }),
    ).toBe(5.6);
  });
  it.each([5.6, 25])(
    "does not double count a live player's %s points",
    (points) => {
      expect(
        currentProjection([{ ...brown, livePoints: points }], points, {
          PHI: "live",
        }),
      ).toBe(Math.max(points, 16.86));
    },
  );
  it("counts out starters and byes as zero future points", () => {
    expect(
      currentProjection(
        [
          {
            ...brown,
            injuryStatus: "Out",
            projectedPoints: null,
            livePoints: 0,
          },
        ],
        0,
        { PHI: "remaining" },
      ),
    ).toBe(0);
    expect(
      currentProjection([{ ...brown, livePoints: 0 }], 0, { PHI: "bye" }),
    ).toBe(0);
  });
  it("does not count bench estimates", () => {
    expect(
      currentProjection([brown, { ...rest, slot: "bench" }], 5.6, {
        PHI: "done",
        KC: "remaining",
      }),
    ).toBe(5.6);
  });
  it("withholds a figure for missing data or a different scored lineup", () => {
    expect(currentProjection([brown], 5.6, null)).toBeNull();
    expect(currentProjection([brown], null, { PHI: "done" })).toBeNull();
    expect(
      currentProjection([{ ...brown, livePoints: null }], 5.6, { PHI: "done" }),
    ).toBeNull();
    expect(
      currentProjection([{ ...brown, projectedPoints: null }], 0, {
        PHI: "remaining",
      }),
    ).toBeNull();
    expect(
      currentProjection([brown], 5.6, { PHI: "done" }, ["different-player"]),
    ).toBeNull();
  });
});

it("scopes game states to the requested week and does not call unknown states finished", () => {
  const schedule = parseWeekSchedule(
    [
      { week: 1, home: "PHI", away: "DAL", status: "complete" },
      { week: 2, home: "PHI", away: "KC", status: "pre_game" },
      { week: 1, home: "KC", away: "BUF", status: "halftime" },
    ],
    1,
  );
  expect(schedule.PHI).toBe("done");
  expect(schedule.KC).toBe("live");
  expect(schedule.CHI).toBe("bye");
  expect(() => parseWeekSchedule([], 1)).toThrow();
  expect(() => parseWeekSchedule({}, 1)).toThrow();
});
