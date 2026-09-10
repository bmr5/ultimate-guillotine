/**
 * The live-score derivations: how a score is spelled, which figure the board emphasises, and
 * which stamp the header leads with. Pure functions over plain rows.
 *
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { BoardTeam } from "../types";
import {
  formatScore,
  hasLiveScores,
  newestScoreSyncedAt,
  resolveCardEmphasis,
  SCORE_ZERO_TEXT,
} from "./score";

const team = (over: Partial<BoardTeam> & { teamId: number }): BoardTeam =>
  ({
    teamName: `Team ${over.teamId}`,
    ownerName: `owner${over.teamId}`,
    sleeperRosterId: over.teamId,
    score: null,
    scoreSyncedAt: null,
    projectedPoints: 100,
    coveragePct: 100,
    isProvisional: false,
    projectionComputedAt: null,
    faabRemaining: 50,
    pointsFor: 0,
    startersProjected: 9,
    starterSlots: 9,
    isEliminated: false,
    eliminatedWeek: null,
    eliminationSource: null,
    emptySlots: null,
    isRosterFrozen: false,
    risk: null,
    roster: [],
    ...over,
  }) as BoardTeam;

describe("formatScore", () => {
  it("spells a score to one decimal, like every other number on the board", () => {
    expect(formatScore(84.24)).toBe("84.2");
    expect(formatScore(112)).toBe("112.0");
  });

  it("renders a scoreless team as 0.0 rather than as an em dash", () => {
    // Ben's ruling is explicit: a score of nothing is a real answer, and the week starts there.
    expect(formatScore(0)).toBe(SCORE_ZERO_TEXT);
  });

  it("renders a week with no score row as 0.0 too", () => {
    // Before the first sync of a week there is no row, and "nobody has scored yet" is exactly
    // as true then as it is at kickoff. The em dash belongs to the projection alone.
    expect(formatScore(null)).toBe(SCORE_ZERO_TEXT);
    expect(formatScore(null)).not.toBe("—");
  });
});

describe("hasLiveScores", () => {
  it("is false on an empty board", () => {
    expect(hasLiveScores([])).toBe(false);
  });

  it("is false before kickoff, when every row says zero", () => {
    expect(
      hasLiveScores([
        team({ teamId: 1, score: 0 }),
        team({ teamId: 2, score: 0 }),
      ]),
    ).toBe(false);
  });

  it("is false when the week has no score rows at all", () => {
    expect(hasLiveScores([team({ teamId: 1 }), team({ teamId: 2 })])).toBe(
      false,
    );
  });

  it("turns true on the first point anybody scores", () => {
    expect(
      hasLiveScores([
        team({ teamId: 1, score: 0 }),
        team({ teamId: 2, score: 0.5 }),
      ]),
    ).toBe(true);
  });
});

describe("resolveCardEmphasis", () => {
  it("leads with the projection until somebody scores", () => {
    // A wall of `0.0` in the large type, where the number people actually read on a Saturday
    // is the projection, is the thing this rule exists to prevent.
    expect(resolveCardEmphasis([team({ teamId: 1, score: 0 })])).toBe(
      "projection",
    );
  });

  it("leads with the score once the week is live", () => {
    expect(resolveCardEmphasis([team({ teamId: 1, score: 12.2 })])).toBe(
      "score",
    );
  });

  it("is one answer for the whole board, not one per team", () => {
    // A scoreless team on a live Sunday still emphasises its score: the question is what the
    // week is doing, and eighteen cards sized differently would not line up down the grid.
    expect(
      resolveCardEmphasis([
        team({ teamId: 1, score: 0 }),
        team({ teamId: 2, score: 88.1 }),
      ]),
    ).toBe("score");
  });
});

describe("newestScoreSyncedAt", () => {
  it("is null when no team has a score row", () => {
    expect(newestScoreSyncedAt([team({ teamId: 1 })])).toBeNull();
  });

  it("takes the newest stamp across the week's rows", () => {
    expect(
      newestScoreSyncedAt([
        team({ teamId: 1, scoreSyncedAt: "2026-09-13T17:30:00Z" }),
        team({ teamId: 2, scoreSyncedAt: "2026-09-13T17:31:00Z" }),
        team({ teamId: 3, scoreSyncedAt: "2026-09-13T17:29:00Z" }),
      ]),
    ).toBe(Date.parse("2026-09-13T17:31:00Z"));
  });

  it("skips a stamp it cannot parse rather than poisoning the fold with NaN", () => {
    expect(
      newestScoreSyncedAt([
        team({ teamId: 1, scoreSyncedAt: "not a time" }),
        team({ teamId: 2, scoreSyncedAt: "2026-09-13T17:30:00Z" }),
      ]),
    ).toBe(Date.parse("2026-09-13T17:30:00Z"));
  });

  it("is null when every stamp is unparseable", () => {
    expect(
      newestScoreSyncedAt([team({ teamId: 1, scoreSyncedAt: "" })]),
    ).toBeNull();
  });
});
