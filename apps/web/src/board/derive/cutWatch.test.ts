// @vitest-environment node
import { describe, expect, it } from "vitest";

import type { BoardTeam } from "../types";
import { cutWatch } from "./cutWatch";

const team = (
  teamId: number,
  overrides: Partial<BoardTeam> = {},
): BoardTeam => ({
  teamId,
  teamName: `Team ${teamId}`,
  ownerName: `Owner ${teamId}`,
  sleeperRosterId: teamId,
  score: 0,
  scoreSyncedAt: null,
  projectedPoints: teamId * 10,
  coveragePct: 100,
  isProvisional: false,
  projectionComputedAt: null,
  faabRemaining: 100,
  pointsFor: 0,
  startersProjected: 9,
  starterSlots: 9,
  isEliminated: false,
  eliminatedWeek: null,
  eliminationSource: null,
  emptySlots: 0,
  isRosterFrozen: false,
  risk: {
    probability: 0.2,
    adverseEvent: "gulag_entry",
    isEstimated: false,
    settled: false,
    snapshotAt: "2026-09-10T12:00:00Z",
  },
  roster: [],
  ...overrides,
});

describe("cutWatch", () => {
  it("uses projections before scoring, excluding eliminated teams", () => {
    const result = cutWatch(
      [team(4), team(2), team(3), team(1), team(0, { isEliminated: true })],
      1,
    );
    expect(result).toMatchObject({
      kind: "ranked",
      basis: "projection",
      tied: false,
    });
    if (result.kind !== "ranked") throw new Error("Expected rankings");
    expect(result.teams.map(({ team, gap }) => [team.teamId, gap])).toEqual([
      [1, 20],
      [2, 10],
    ]);
  });

  it("switches to scores and keeps zero and negative scores in the running", () => {
    const result = cutWatch(
      [
        team(1, { score: 15 }),
        team(2, { score: -2 }),
        team(3),
        team(4, { score: 10 }),
      ],
      1,
    );
    expect(result).toMatchObject({ kind: "ranked", basis: "score" });
    if (result.kind !== "ranked") throw new Error("Expected rankings");
    expect(result.teams.map(({ team, gap }) => [team.teamId, gap])).toEqual([
      [2, 12],
      [3, 10],
    ]);
  });

  it("excludes the current gulag pairing from next week's entrants", () => {
    const gulag = [team(1), team(2)].map((t) => ({
      ...t,
      risk: { ...t.risk!, adverseEvent: "gulag_loss" as const },
    }));
    const result = cutWatch([...gulag, team(3), team(4), team(5)], 2);
    if (result.kind !== "ranked") throw new Error("Expected rankings");
    expect(result.teams.map(({ team }) => team.teamId)).toEqual([3, 4]);
  });

  it("waits when the pairing or any eligible team's points are missing", () => {
    expect(cutWatch([team(1), team(2), team(3)], 2).kind).toBe("waiting");
    expect(
      cutWatch([team(1), team(2), team(3, { projectedPoints: null })], 1).kind,
    ).toBe("waiting");
    expect(
      cutWatch([team(1, { score: 5 }), team(2), team(3, { score: null })], 1)
        .kind,
    ).toBe("waiting");
  });

  it("includes ties across the boundary without claiming an arbitrary team is safe", () => {
    const result = cutWatch(
      [team(1), team(2), team(3, { projectedPoints: 20 }), team(4)],
      1,
    );
    if (result.kind !== "ranked") throw new Error("Expected rankings");
    expect(result.tied).toBe(true);
    expect(result.teams.map(({ team, gap }) => [team.teamId, gap])).toEqual([
      [1, null],
      [2, null],
      [3, null],
    ]);
    expect(
      cutWatch(
        [
          team(1),
          team(2, { projectedPoints: 10 }),
          team(3, { projectedPoints: 10 }),
        ],
        1,
      ).kind,
    ).toBe("ranked");
  });

  it("orders a broad scoreless tie by projection for the matchup preview", () => {
    const teams = Array.from({ length: 18 }, (_, index) =>
      team(index + 1, { score: index < 12 ? 0 : 10 }),
    );
    const result = cutWatch(teams.reverse(), 1);
    expect(result).toMatchObject({
      kind: "ranked",
      basis: "score",
      tied: true,
    });
    if (result.kind !== "ranked") throw new Error("Expected rankings");
    expect(result.teams).toHaveLength(12);
    expect(result.teams.slice(0, 2).map(({ team }) => team.teamId)).toEqual([
      1, 2,
    ]);
    expect(result.teams.every(({ gap }) => gap === null)).toBe(true);
  });
});
