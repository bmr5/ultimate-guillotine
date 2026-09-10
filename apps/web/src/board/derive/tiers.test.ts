import { describe, expect, it } from "vitest";

import type { BoardTeam } from "../types";
import { faabTiers, kMeansThree, richestTeam, tierBlurb } from "./tiers";

const team = (teamId: number, faabRemaining: number | null): BoardTeam =>
  ({
    teamId,
    ownerName: `Owner ${teamId}`,
    teamName: `Team ${teamId}`,
    faabRemaining,
  }) as BoardTeam;

describe("kMeansThree", () => {
  it("finds three natural clusters rather than equal thirds", () => {
    // Two whales, three middling, five paupers: terciles would split 3/3/4.
    const values = [900, 880, 400, 380, 360, 40, 30, 20, 10, 0];
    const labels = kMeansThree(values);
    expect(labels).toEqual([2, 2, 1, 1, 1, 0, 0, 0, 0, 0]);
  });

  it("is deterministic and handles a tie by promoting", () => {
    expect(kMeansThree([100, 100, 100])).toEqual([2, 2, 2]);
    expect(kMeansThree([])).toEqual([]);
  });
});

describe("faabTiers", () => {
  it("labels the clusters rich, medium and poor, richest first within a tier", () => {
    const tiers = faabTiers([
      team(1, 10),
      team(2, 900),
      team(3, 400),
      team(4, 880),
      team(5, 0),
      team(6, null),
    ]);
    expect(tiers.tiers.map((t) => t.label)).toEqual(["Rich", "Medium", "Poor"]);
    expect(tiers.tiers[0].teams.map((t) => t.teamId)).toEqual([2, 4]);
    expect(tiers.tiers[0]).toMatchObject({ min: 880, max: 900, centroid: 890 });
    expect(tiers.tiers[1].teams.map((t) => t.teamId)).toEqual([3]);
    expect(tiers.tiers[2].teams.map((t) => t.teamId)).toEqual([1, 5]);
    expect(tiers.unknown.map((t) => t.teamId)).toEqual([6]);
    expect(tiers.method).toContain("k-means");
  });
});

describe("tierBlurb", () => {
  it("names the richest and the poorest so the bragging rights are explicit", () => {
    const tiers = faabTiers([
      team(1, 10),
      team(2, 900),
      team(3, 400),
      team(4, 880),
      team(5, 0),
    ]);
    expect(tierBlurb(tiers.tiers[0])).toContain(
      "Owner 2 leads the league at $900",
    );
    expect(tierBlurb(tiers.tiers[1])).toContain("Owner 3 is one good week");
    expect(tierBlurb(tiers.tiers[2])).toContain(
      "Owner 5 brings up the rear at $0",
    );
    expect(richestTeam(tiers)?.teamId).toBe(2);
    expect(tierBlurb(faabTiers([]).tiers[0])).toBe("Nobody here. Yet.");
  });
});
