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
  const curve = faabCurve([710, 400, 40]);

  it("follows the distance from the mean and names the extremes", () => {
    expect(
      bandTagline({ from: 700, to: 750 }, curve, [whale], whale, broke),
    ).toBe(
      "The penthouse. FAAB is not a constraint, it is a personality. Whale has the fattest wallet in the league.",
    );
    expect(
      bandTagline({ from: 0, to: 50 }, curve, [broke], whale, broke),
    ).toContain("Broke is the poorest team in the league.");
    expect(
      bandTagline(
        { from: 350, to: 400 },
        curve,
        [team(2, "Mid", 380)],
        whale,
        broke,
      ),
    ).toContain("middle of the pack");
  });

  it("has words for an empty band too", () => {
    expect(bandTagline({ from: 750, to: 800 }, curve, [], whale, broke)).toBe(
      "Nobody up here. The air is thin.",
    );
  });
});
