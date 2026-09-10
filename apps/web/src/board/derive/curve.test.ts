import { describe, expect, it } from "vitest";

import { curveHeightAt, faabCurve, mean, standardDeviation } from "./curve";

describe("faabCurve", () => {
  it("fits a normal curve with its peak at the mean", () => {
    const curve = faabCurve([100, 200, 300, 400, 500]);
    expect(mean([100, 200, 300, 400, 500])).toBe(300);
    expect(standardDeviation([100, 200, 300, 400, 500])).toBeCloseTo(141.42, 1);
    expect(curve.mean).toBe(300);
    expect(curveHeightAt(curve, 300)).toBe(1);
    expect(curveHeightAt(curve, 300 + curve.sd)).toBeCloseTo(Math.exp(-0.5), 5);
    expect(curve.from).toBeLessThanOrEqual(100);
    expect(curve.from).toBeGreaterThanOrEqual(0);
    expect(curve.to).toBeGreaterThan(500);
    expect(curve.points[0].x).toBe(curve.from);
    expect(curve.points[curve.points.length - 1].x).toBe(curve.to);
  });

  it("survives a league with no spread and an empty league", () => {
    expect(faabCurve([250, 250, 250]).sd).toBe(1);
    expect(faabCurve([]).points.length).toBe(81);
  });
});
