/**
 * The bell curve under the FAAB tiers: a normal distribution fitted to the league's FAAB
 * (mean and population standard deviation), with every team marked where it falls.
 * Ben (2026-09-10): "at the bottom add like a bell curve chart or something just for fun".
 */

export interface CurvePoint {
  x: number;
  y: number;
}

export interface FaabCurve {
  mean: number;
  sd: number;
  /**
   * The x-range the curve is drawn over. Ben (2026-09-10): a fixed scale from $0 to the next
   * $100 above the richest team, so $710 at the top draws the axis to $800.
   */
  from: number;
  to: number;
  /** Density samples along `[from, to]`, `y` normalised so the peak is 1. */
  points: CurvePoint[];
}

export function mean(values: readonly number[]): number {
  return values.length === 0
    ? 0
    : values.reduce((sum, v) => sum + v, 0) / values.length;
}

export function standardDeviation(values: readonly number[]): number {
  if (values.length === 0) return 0;
  const m = mean(values);
  return Math.sqrt(
    values.reduce((sum, v) => sum + (v - m) ** 2, 0) / values.length,
  );
}

/** Density of a normal distribution at `x`, before normalisation. */
function density(x: number, m: number, sd: number): number {
  return Math.exp(-((x - m) ** 2) / (2 * sd * sd));
}

/** The axis ends at the next $100 above the richest team … */
export const AXIS_END_STEP = 100;
/** … and is ruled, banded and ticked every $50 (Ben, 2026-09-10: "ticks in obvious $50s"). */
export const AXIS_STEP = 50;

export function faabCurve(values: readonly number[], samples = 80): FaabCurve {
  const m = mean(values);
  // A league where everyone holds the same amount has no spread; a token width keeps a
  // curve on the page rather than a division by zero.
  const sd = Math.max(standardDeviation(values), 1);
  const hi = values.length ? Math.max(...values) : 0;
  const from = 0;
  const to = Math.max(
    AXIS_END_STEP,
    Math.ceil(hi / AXIS_END_STEP) * AXIS_END_STEP,
  );
  const points: CurvePoint[] = [];
  for (let i = 0; i <= samples; i += 1) {
    const x = from + ((to - from) * i) / samples;
    points.push({ x, y: density(x, m, sd) });
  }
  return { mean: m, sd, from, to, points };
}

/** Where a value sits on the curve, `y` in the same 0–1 scale as the samples. */
export function curveHeightAt(curve: FaabCurve, x: number): number {
  return density(x, curve.mean, curve.sd);
}

export interface CurveBand {
  from: number;
  to: number;
}

/** The $50 bands the axis is ruled into, `[from, to)` except the last, which is closed. */
export function curveBands(curve: FaabCurve): CurveBand[] {
  const bands: CurveBand[] = [];
  for (let from = curve.from; from < curve.to; from += AXIS_STEP) {
    bands.push({ from, to: Math.min(curve.to, from + AXIS_STEP) });
  }
  return bands;
}

export function inBand(value: number, band: CurveBand, last: boolean): boolean {
  return value >= band.from && (last ? value <= band.to : value < band.to);
}
