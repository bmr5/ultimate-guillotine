/**
 * The odds are arithmetic over the Daily's stored JSON with no DOM in it, so this runs under
 * node like the other derive modules.
 *
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { Json, TeamRisk } from "../types";
import {
  formatRiskPercent,
  MONTE_CARLO_SENTENCE,
  resolveRiskDisplay,
  riskByTeamId,
} from "./odds";

const SNAPSHOT_AT = "2026-09-10T15:15:23Z";

/** One entry of `survival_snapshots.results`, as `results_payload` in the Daily writes it. */
const entry = (over: Record<string, unknown> = {}): Json =>
  ({
    team_id: 7,
    label: "Ben R",
    points: 7.8,
    projected_final: 88.2,
    pending: 8,
    adverse_event: "gulag_entry",
    probability: 0.37,
    is_estimated: false,
    ...over,
  }) as Json;

const snapshot = (results: Json) => ({ snapshot_at: SNAPSHOT_AT, results });

const risk = (over: Partial<TeamRisk> = {}): TeamRisk => ({
  probability: 0.37,
  adverseEvent: "gulag_entry",
  isEstimated: false,
  settled: false,
  snapshotAt: SNAPSHOT_AT,
  ...over,
});

describe("riskByTeamId", () => {
  it("keys one team's odds by its id and stamps when they were computed", () => {
    const risks = riskByTeamId(snapshot([entry()]));
    expect(risks.get(7)).toEqual(risk());
  });

  it("is empty before the week's first Daily", () => {
    expect(riskByTeamId(null).size).toBe(0);
  });

  it("is empty when the payload is not the list the Daily writes", () => {
    expect(riskByTeamId(snapshot({ team_id: 7 })).size).toBe(0);
    expect(riskByTeamId(snapshot("[]")).size).toBe(0);
  });

  it("drops an entry with no usable team id or probability", () => {
    const risks = riskByTeamId(
      snapshot([
        entry({ team_id: "7" }),
        entry({ team_id: 8, probability: "0.5" }),
        entry({ team_id: 9, probability: Number.NaN }),
        "not an entry",
        null,
      ]),
    );
    expect(risks.size).toBe(0);
  });

  it("keeps an event this build has no word for, with no name on it", () => {
    const risks = riskByTeamId(
      snapshot([entry({ adverse_event: "relegation" })]),
    );
    expect(risks.get(7)?.adverseEvent).toBeNull();
    expect(risks.get(7)?.probability).toBe(0.37);
  });

  it("reads a malformed estimate flag as not estimated", () => {
    const risks = riskByTeamId(snapshot([entry({ is_estimated: "yes" })]));
    expect(risks.get(7)?.isEstimated).toBe(false);
  });

  it("calls the odds settled once no live team has a starter left to play", () => {
    const risks = riskByTeamId(
      snapshot([
        entry({ team_id: 7, pending: 0, probability: 1 }),
        entry({ team_id: 8, pending: 0, probability: 0 }),
      ]),
    );
    expect(risks.get(7)?.settled).toBe(true);
    expect(risks.get(8)?.settled).toBe(true);
  });

  it("does not call the odds settled while any team still has a starter to play", () => {
    const risks = riskByTeamId(
      snapshot([
        entry({ team_id: 7, pending: 0 }),
        entry({ team_id: 8, pending: 3 }),
      ]),
    );
    expect(risks.get(7)?.settled).toBe(false);
  });

  it("does not call the odds settled on a pending count it cannot read", () => {
    const risks = riskByTeamId(snapshot([entry({ pending: "0" })]));
    expect(risks.get(7)?.settled).toBe(false);
  });
});

/**
 * Mirrors `percent()` in the Daily's `summary/render.py`, so a figure on the board and the same
 * figure in the chat never disagree by a rounding rule.
 */
describe("formatRiskPercent", () => {
  it("rounds to a whole percentage, halves up", () => {
    expect(formatRiskPercent(0.37, false)).toBe("37%");
    expect(formatRiskPercent(0.125, false)).toBe("13%");
  });

  it("names the tails rather than rounding them away", () => {
    expect(formatRiskPercent(0.004, false)).toBe("<1%");
    expect(formatRiskPercent(0.996, false)).toBe(">99%");
    expect(formatRiskPercent(0, false)).toBe("0%");
    expect(formatRiskPercent(1, false)).toBe("100%");
  });

  it("uses words once every game is final", () => {
    expect(formatRiskPercent(1, true)).toBe("locked");
    expect(formatRiskPercent(0, true)).toBe("safe");
    // Settled odds are 0 or 1 by construction; anything else still reads as a percentage.
    expect(formatRiskPercent(0.5, true)).toBe("50%");
  });
});

describe("resolveRiskDisplay", () => {
  it("says nothing for a team with no odds", () => {
    expect(resolveRiskDisplay(null)).toBeNull();
  });

  it("names the gulag and the chance of entering it", () => {
    const display = resolveRiskDisplay(risk());
    expect(display?.text).toBe("Gulag 37%");
    expect(display?.label).toBe("Chance of entering the gulag: 37%");
  });

  it("calls losing the gulag, and the plain cut, a cut", () => {
    expect(
      resolveRiskDisplay(risk({ adverseEvent: "gulag_loss", probability: 0.84 }))
        ?.text,
    ).toBe("Cut 84%");
    expect(
      resolveRiskDisplay(risk({ adverseEvent: "cut", probability: 0.12 }))?.text,
    ).toBe("Cut 12%");
  });

  it("names the final's loser the runner-up", () => {
    expect(
      resolveRiskDisplay(risk({ adverseEvent: "title_loss", probability: 0.4 }))
        ?.text,
    ).toBe("Runner-up 40%");
  });

  it("falls back to a plain risk for an event it has no word for", () => {
    const display = resolveRiskDisplay(risk({ adverseEvent: null }));
    expect(display?.text).toBe("Risk 37%");
    expect(display?.label).toBe(
      "Chance of the week going against this team: 37%",
    );
  });

  it("colours the chip by the Daily's own thresholds", () => {
    expect(resolveRiskDisplay(risk({ probability: 0.5 }))?.tone).toBe(
      "destructive",
    );
    expect(resolveRiskDisplay(risk({ probability: 0.2 }))?.tone).toBe(
      "primary",
    );
    expect(resolveRiskDisplay(risk({ probability: 0.19 }))?.tone).toBe("muted");
  });

  it("reads as a result rather than a forecast once every game is final", () => {
    const locked = resolveRiskDisplay(risk({ probability: 1, settled: true }));
    expect(locked?.text).toBe("Gulag locked");
    expect(locked?.tone).toBe("destructive");
    const safe = resolveRiskDisplay(risk({ probability: 0, settled: true }));
    expect(safe?.text).toBe("Gulag safe");
    expect(safe?.tone).toBe("muted");
  });

  it("credits the Daily's simulation in the description", () => {
    expect(resolveRiskDisplay(risk())?.description).toContain(
      MONTE_CARLO_SENTENCE,
    );
    expect(MONTE_CARLO_SENTENCE).toMatch(/Monte Carlo/);
  });

  it("admits when a starter was simulated at his position's median", () => {
    expect(
      resolveRiskDisplay(risk({ isEstimated: true }))?.description,
    ).toMatch(/median/);
    expect(resolveRiskDisplay(risk())?.description).not.toMatch(/median/);
  });
});
