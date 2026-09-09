import type { BoardTeam } from "../types";

/** The same 95 percent gate the data layer and Game Pulse use. */
export const COVERAGE_GATE_PCT = 95;

/** At or below this the projection is not a number the board is willing to show. */
export const NO_COVERAGE_PCT = 0;

/** Decimals the card shows; a projection is never rendered with more precision than this. */
export const PROJECTION_DECIMALS = 1;

/** Em dash, the board's stand-in for "there is no number here". */
export const PROJECTION_UNAVAILABLE_TEXT = "—";

/** Screen-reader and tooltip wording for the small badge beside a below-gate projection. */
export const PARTIAL_COVERAGE_LABEL = "Partial projection coverage";

/** Wording for the em dash state, and for the strict rendering of a below-gate projection. */
export const PROJECTION_UNAVAILABLE_LABEL = "Projection unavailable";

/** The second sentence of the badge's tooltip; constant, so it is stated once. */
export const PARTIAL_COVERAGE_EXPLANATION_SUFFIX =
  "The number counts the players Sleeper has projected.";

export type CoverageExplanationInput = Pick<
  BoardTeam,
  "startersProjected" | "starterSlots" | "coveragePct"
>;

/**
 * A percentage a reader would write: `100`, not `100.00`; `66.7`, not `66.70`. `coverage_pct` is
 * a `numeric(5, 2)`, so the raw figure carries two decimals that say nothing.
 */
function formatCoveragePct(coveragePct: number): string {
  return String(Number(coveragePct.toFixed(1)));
}

/**
 * Why the `partial` badge is on this card, in one sentence.
 *
 * Ben's card change 3: the badge said *that* the projection was partial and nothing about why,
 * so the tooltip names the two figures behind it — how many starters Sleeper has a projection
 * for, out of how many slots — and says what the big number therefore counts.
 *
 * null when the projection row is missing either count, which is also the only state in which
 * there is no sentence to write: without a row there is no partial projection to explain.
 */
export function partialCoverageExplanation(
  input: CoverageExplanationInput,
): string | null {
  const { startersProjected, starterSlots, coveragePct } = input;
  if (
    startersProjected === null ||
    starterSlots === null ||
    coveragePct === null
  ) {
    return null;
  }
  const coverage = formatCoveragePct(coveragePct);
  return (
    `Only ${startersProjected} of ${starterSlots} starters have a projection ` +
    `(${coverage}%). ${PARTIAL_COVERAGE_EXPLANATION_SUFFIX}`
  );
}

/**
 * The single switch between the two below-gate treatments Ben weighed. Off (the shipped
 * behaviour) shows the projected number with a small `partial` badge, because the board does
 * not caveat projections heavily. On, a below-gate projection is suppressed entirely and reads
 * `Projection unavailable` — the strict wording, kept available but not the default.
 */
export const STRICT_COVERAGE_GATE = false;

export type ProjectionCaveat = "partial" | "unavailable";

export interface ProjectionDisplay {
  kind: "value" | "unavailable";
  points: number | null;
  text: string;
  caveat: ProjectionCaveat | null;
  caveatLabel: string | null;
}

export type ProjectionInput = Pick<
  BoardTeam,
  "projectedPoints" | "coveragePct" | "isProvisional"
>;

const UNAVAILABLE_DISPLAY: ProjectionDisplay = {
  kind: "unavailable",
  points: null,
  text: PROJECTION_UNAVAILABLE_TEXT,
  caveat: "unavailable",
  caveatLabel: PROJECTION_UNAVAILABLE_LABEL,
};

/**
 * The single place the board decides how a projection is displayed. Three states:
 * at or above the gate → bare number; above zero but below the gate → number plus caveat
 * badge; zero coverage or no row → em dash. Never zero for a missing projection.
 *
 * `strict` defaults to the exported flag; pass it explicitly only to preview the other
 * treatment, in which case a below-gate projection collapses to the em dash state too.
 */
export function resolveProjectionDisplay(
  input: ProjectionInput,
  strict: boolean = STRICT_COVERAGE_GATE,
): ProjectionDisplay {
  const { projectedPoints, coveragePct, isProvisional } = input;

  if (
    projectedPoints === null ||
    coveragePct === null ||
    coveragePct <= NO_COVERAGE_PCT
  ) {
    return { ...UNAVAILABLE_DISPLAY };
  }

  // The flag can lag the figure it summarises, so either one below the gate means partial.
  const isPartial = isProvisional || coveragePct < COVERAGE_GATE_PCT;
  if (isPartial && strict) {
    return { ...UNAVAILABLE_DISPLAY };
  }

  return {
    kind: "value",
    points: projectedPoints,
    text: projectedPoints.toFixed(PROJECTION_DECIMALS),
    caveat: isPartial ? "partial" : null,
    caveatLabel: isPartial ? PARTIAL_COVERAGE_LABEL : null,
  };
}
