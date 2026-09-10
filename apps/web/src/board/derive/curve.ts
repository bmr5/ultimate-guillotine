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
  /** The x-range the curve is drawn over: two deviations past the extremes, floored at zero. */
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

export function faabCurve(values: readonly number[], samples = 80): FaabCurve {
  const m = mean(values);
  // A league where everyone holds the same amount has no spread; a token width keeps a
  // curve on the page rather than a division by zero.
  const sd = Math.max(standardDeviation(values), 1);
  const lo = values.length ? Math.min(...values) : 0;
  const hi = values.length ? Math.max(...values) : 0;
  const from = Math.max(0, Math.min(lo, m - 2 * sd));
  const to = Math.max(hi, m + 2 * sd);
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
