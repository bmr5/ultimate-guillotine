import { describe, expect, it } from "vitest";

import type { BoardTeam } from "../types";
import { bandTagline } from "./bandTagline";
import { faabCurve } from "./curve";

const team = (
  teamId: number,
  ownerName: string,
  faabRemaining: number,
): BoardTeam =>
  ({ teamId, ownerName, teamName: `T${teamId}`, faabRemaining }) as BoardTeam;

describe("bandTagline", () => {
  const whale = team(1, "Whale", 710);
  const broke = team(3, "Broke", 40);
  const wide = faabCurve([710, 400, 40]);
  const tight = faabCurve([710, 400, 380, 390, 410, 40]);

  it("follows the band's distance from the mean", () => {
    // Three teams make a wide deviation, so $700 is "loaded"; six bunched teams make it
    // the penthouse.
    expect(bandTagline({ from: 700, to: 750 }, wide, [whale], null, null)).toBe(
      "Comfortably loaded. Can outbid anyone who blinks.",
    );
    expect(
      bandTagline({ from: 700, to: 750 }, tight, [whale], null, null),
    ).toContain("The penthouse");
    expect(
      bandTagline(
        { from: 350, to: 400 },
        wide,
        [team(2, "Mid", 380)],
        null,
        null,
      ),
    ).toContain("middle of the pack");
  });

  it("names the richest and the poorest when they live in the band", () => {
    expect(
      bandTagline({ from: 700, to: 750 }, wide, [whale], whale, broke),
    ).toContain("Whale has the fattest wallet in the league.");
    expect(
      bandTagline({ from: 0, to: 50 }, wide, [broke], whale, broke),
    ).toContain("Broke is the poorest team in the league.");
  });

  it("has words for an empty band too", () => {
    expect(bandTagline({ from: 750, to: 800 }, wide, [], whale, broke)).toBe(
      "Nobody up here. The air is thin.",
    );
  });
});
