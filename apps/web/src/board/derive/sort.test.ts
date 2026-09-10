/**
 * Sorting is comparisons over plain numbers and strings, so it runs under node like the other
 * derive modules.
 *
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { BoardTeam, SortMode } from "../types";
import { SORT_MODES } from "../types";
import {
  compareTeams,
  partitionByElimination,
  selectEffectiveSortMode,
  sortBoardTeams,
  sortValue,
} from "./sort";

const team = (over: Partial<BoardTeam> & { teamId: number }): BoardTeam => ({
  isRosterFrozen: false,
  risk: null,
  teamName: `Team ${over.teamId}`,
  ownerName: `Owner ${over.teamId}`,
  sleeperRosterId: over.teamId,
  score: null,
  scoreSyncedAt: null,
  projectedPoints: 100,
  coveragePct: 100,
  isProvisional: false,
  projectionComputedAt: "2026-09-09T12:00:00Z",
  faabRemaining: 50,
  pointsFor: 200,
  startersProjected: 9,
  starterSlots: 9,
  isEliminated: false,
  eliminatedWeek: null,
  eliminationSource: null,
  emptySlots: null,
  roster: [],
  ...over,
});

/**
 * One row per sort key, so every assertion below runs against all three modes rather than
 * against whichever one happened to get written out by hand. `missing` is null for a key the
 * board type cannot leave empty.
 */
interface SortModeCase {
  mode: SortMode;
  /** Produces a team whose sort key for this mode is `value`. */
  withKey: (teamId: number, value: number) => BoardTeam;
  /** Produces a team with no comparable key for this mode, or null when the key is required. */
  withoutKey: ((teamId: number) => BoardTeam) | null;
}

const SORT_MODE_CASES: SortModeCase[] = [
  {
    mode: "projection",
    withKey: (teamId, value) => team({ teamId, projectedPoints: value }),
    withoutKey: (teamId) =>
      team({ teamId, projectedPoints: null, coveragePct: null }),
  },
  {
    mode: "score",
    withKey: (teamId, value) => team({ teamId, score: value }),
    // No score row for the week at all. Not coerced to zero: eighteen teams with nothing to
    // sort by is not eighteen teams tied on nothing, and they fall to the same tie-breaks.
    withoutKey: (teamId) => team({ teamId, score: null }),
  },
  {
    mode: "faab",
    withKey: (teamId, value) => team({ teamId, faabRemaining: value }),
    withoutKey: (teamId) => team({ teamId, faabRemaining: null }),
  },
  {
    mode: "points_for",
    withKey: (teamId, value) => team({ teamId, pointsFor: value }),
    withoutKey: null,
  },
];

it("covers every sort mode the board exposes", () => {
  expect(SORT_MODE_CASES.map((one) => one.mode)).toEqual([...SORT_MODES]);
});

describe.each(SORT_MODE_CASES)(
  "$mode sort",
  ({ mode, withKey, withoutKey }) => {
    it("orders active teams by the key, descending", () => {
      const { active } = sortBoardTeams(
        [withKey(1, 10), withKey(2, 30), withKey(3, 20)],
        mode,
      );
      expect(active.map((t) => t.teamId)).toEqual([2, 3, 1]);
    });

    it("reads the key back through sortValue", () => {
      expect(sortValue(withKey(1, 42), mode)).toBe(42);
    });

    it("groups eliminated teams after every active team", () => {
      const teams = [
        { ...withKey(1, 999), isEliminated: true, eliminatedWeek: 2 },
        withKey(2, 1),
        { ...withKey(3, 500), isEliminated: true, eliminatedWeek: 5 },
      ];
      const { active, eliminated } = sortBoardTeams(teams, mode);
      expect(active.map((t) => t.teamId)).toEqual([2]);
      // Most recently eliminated reads first, whatever the sort key says.
      expect(eliminated.map((t) => t.teamId)).toEqual([3, 1]);
    });

    it("compares a stronger key ahead of a weaker one in both directions", () => {
      const strong = withKey(1, 30);
      const weak = withKey(2, 10);
      expect(compareTeams(strong, weak, mode)).toBeLessThan(0);
      expect(compareTeams(weak, strong, mode)).toBeGreaterThan(0);
      expect(compareTeams(strong, strong, mode)).toBe(0);
    });

    if (withoutKey) {
      it("sorts a missing key last instead of treating it as zero", () => {
        const { active } = sortBoardTeams(
          [withoutKey(1), withKey(2, -5), withKey(3, 40)],
          mode,
        );
        expect(active.map((t) => t.teamId)).toEqual([3, 2, 1]);
        expect(sortValue(withoutKey(1), mode)).toBeNull();
      });

      it("orders two missing keys against each other deterministically", () => {
        const first = withoutKey(1);
        const second = withoutKey(2);
        expect(compareTeams(first, second, mode)).toBeLessThan(0);
        expect(compareTeams(second, first, mode)).toBeGreaterThan(0);
      });
    }
  },
);

describe("sortBoardTeams", () => {
  it("sorts active teams by projection descending", () => {
    const { active } = sortBoardTeams(
      [
        team({ teamId: 1, projectedPoints: 90 }),
        team({ teamId: 2, projectedPoints: 130 }),
        team({ teamId: 3, projectedPoints: 110 }),
      ],
      "projection",
    );
    expect(active.map((t) => t.teamId)).toEqual([2, 3, 1]);
  });

  it("sorts by FAAB descending", () => {
    const { active } = sortBoardTeams(
      [
        team({ teamId: 1, faabRemaining: 10 }),
        team({ teamId: 2, faabRemaining: 99 }),
        team({ teamId: 3, faabRemaining: 55 }),
      ],
      "faab",
    );
    expect(active.map((t) => t.teamId)).toEqual([2, 3, 1]);
  });

  it("sorts by points for descending", () => {
    const { active } = sortBoardTeams(
      [
        team({ teamId: 1, pointsFor: 305 }),
        team({ teamId: 2, pointsFor: 180 }),
        team({ teamId: 3, pointsFor: 402 }),
      ],
      "points_for",
    );
    expect(active.map((t) => t.teamId)).toEqual([3, 1, 2]);
  });

  it("puts a missing projection last instead of treating it as zero", () => {
    const { active } = sortBoardTeams(
      [
        team({
          teamId: 1,
          projectedPoints: null,
          coveragePct: null,
          isProvisional: true,
        }),
        team({ teamId: 2, projectedPoints: -5 }),
        team({ teamId: 3, projectedPoints: 40 }),
      ],
      "projection",
    );
    expect(active.map((t) => t.teamId)).toEqual([3, 2, 1]);
  });

  it("groups eliminated teams after every active team under every sort", () => {
    const teams = [
      team({
        teamId: 1,
        projectedPoints: 200,
        isEliminated: true,
        eliminatedWeek: 2,
      }),
      team({ teamId: 2, projectedPoints: 10 }),
      team({
        teamId: 3,
        projectedPoints: 180,
        isEliminated: true,
        eliminatedWeek: 5,
      }),
    ];
    const byProjection = sortBoardTeams(teams, "projection");
    expect(byProjection.active.map((t) => t.teamId)).toEqual([2]);
    expect(byProjection.eliminated.map((t) => t.teamId)).toEqual([3, 1]);

    const byFaab = sortBoardTeams(teams, "faab");
    expect(byFaab.active.map((t) => t.teamId)).toEqual([2]);
    expect(byFaab.eliminated.map((t) => t.teamId)).toEqual([3, 1]);
  });

  it("orders an unknown elimination week last within the eliminated group", () => {
    const { eliminated } = sortBoardTeams(
      [
        team({ teamId: 1, isEliminated: true, eliminatedWeek: null }),
        team({ teamId: 2, isEliminated: true, eliminatedWeek: 1 }),
        team({ teamId: 3, isEliminated: true, eliminatedWeek: 4 }),
      ],
      "projection",
    );
    expect(eliminated.map((t) => t.teamId)).toEqual([3, 2, 1]);
  });

  it("breaks ties on points for, then team name", () => {
    const { active } = sortBoardTeams(
      [
        team({
          teamId: 1,
          teamName: "Zeta",
          projectedPoints: 100,
          pointsFor: 100,
        }),
        team({
          teamId: 2,
          teamName: "Alpha",
          projectedPoints: 100,
          pointsFor: 100,
        }),
        team({
          teamId: 3,
          teamName: "Beta",
          projectedPoints: 100,
          pointsFor: 300,
        }),
      ],
      "projection",
    );
    expect(active.map((t) => t.teamId)).toEqual([3, 2, 1]);
  });

  it("breaks a same-name, same-points tie on team id so the order is total", () => {
    const twin = { teamName: "Twin", projectedPoints: 100, pointsFor: 100 };
    const { active } = sortBoardTeams(
      [
        team({ teamId: 7, ...twin }),
        team({ teamId: 3, ...twin }),
        team({ teamId: 5, ...twin }),
      ],
      "projection",
    );
    expect(active.map((t) => t.teamId)).toEqual([3, 5, 7]);
  });

  it("does not mutate the input array", () => {
    const teams = [
      team({ teamId: 1, projectedPoints: 10 }),
      team({ teamId: 2, projectedPoints: 20 }),
    ];
    sortBoardTeams(teams, "projection");
    expect(teams.map((t) => t.teamId)).toEqual([1, 2]);
  });

  it("returns the same team objects it was given", () => {
    const one = team({ teamId: 1, projectedPoints: 10 });
    const two = team({ teamId: 2, isEliminated: true, eliminatedWeek: 3 });
    const { active, eliminated } = sortBoardTeams([one, two], "projection");
    expect(active[0]).toBe(one);
    expect(eliminated[0]).toBe(two);
  });
});

describe("partitionByElimination", () => {
  it("splits on the is_eliminated flag", () => {
    const { active, eliminated } = partitionByElimination([
      team({ teamId: 1 }),
      team({ teamId: 2, isEliminated: true, eliminatedWeek: 3 }),
    ]);
    expect(active.map((t) => t.teamId)).toEqual([1]);
    expect(eliminated.map((t) => t.teamId)).toEqual([2]);
  });

  it("keeps the given order within each group and leaves the input alone", () => {
    const teams = [
      team({ teamId: 3 }),
      team({ teamId: 1, isEliminated: true, eliminatedWeek: 2 }),
      team({ teamId: 2 }),
    ];
    const { active, eliminated } = partitionByElimination(teams);
    expect(active.map((t) => t.teamId)).toEqual([3, 2]);
    expect(eliminated.map((t) => t.teamId)).toEqual([1]);
    expect(teams.map((t) => t.teamId)).toEqual([3, 1, 2]);
  });
});

describe("selectEffectiveSortMode", () => {
  it("keeps projection when at least one team has a usable projection", () => {
    expect(
      selectEffectiveSortMode(
        [
          team({ teamId: 1, projectedPoints: null, coveragePct: null }),
          team({ teamId: 2, projectedPoints: 90 }),
        ],
        "projection",
      ),
    ).toEqual({ mode: "projection", fellBack: false });
  });

  it("falls back to points for when no projection is usable", () => {
    expect(
      selectEffectiveSortMode(
        [
          team({ teamId: 1, projectedPoints: null, coveragePct: null }),
          team({ teamId: 2, projectedPoints: null, coveragePct: 0 }),
        ],
        "projection",
      ),
    ).toEqual({ mode: "points_for", fellBack: true });
  });

  it("falls back on an empty board rather than sorting by nothing", () => {
    expect(selectEffectiveSortMode([], "projection")).toEqual({
      mode: "points_for",
      fellBack: true,
    });
  });

  it("never overrides an explicit non-projection sort", () => {
    expect(
      selectEffectiveSortMode(
        [team({ teamId: 1, projectedPoints: null, coveragePct: null })],
        "faab",
      ),
    ).toEqual({ mode: "faab", fellBack: false });
  });
});
