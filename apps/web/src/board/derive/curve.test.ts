import { describe, expect, it } from "vitest";

import {
  curveBands,
  curveHeightAt,
  faabCurve,
  inBand,
  mean,
  standardDeviation,
} from "./curve";

describe("faabCurve", () => {
  it("fits a normal curve with its peak at the mean", () => {
    const curve = faabCurve([100, 200, 300, 400, 500]);
    expect(mean([100, 200, 300, 400, 500])).toBe(300);
    expect(standardDeviation([100, 200, 300, 400, 500])).toBeCloseTo(141.42, 1);
    expect(curve.mean).toBe(300);
    expect(curveHeightAt(curve, 300)).toBe(1);
    expect(curveHeightAt(curve, 300 + curve.sd)).toBeCloseTo(Math.exp(-0.5), 5);
    expect(curve.from).toBe(0);
    expect(curve.to).toBe(500);
    expect(faabCurve([710, 40]).to).toBe(800);
    expect(curve.points[0].x).toBe(curve.from);
    expect(curve.points[curve.points.length - 1].x).toBe(curve.to);
  });

  it("survives a league with no spread and an empty league", () => {
    expect(faabCurve([250, 250, 250]).sd).toBe(1);
    expect(faabCurve([]).points.length).toBe(81);
  });
});

describe("curveBands", () => {
  it("rules the axis in fifties and places a value in exactly one band", () => {
    const curve = faabCurve([710, 40]);
    const bands = curveBands(curve);
    expect(bands).toHaveLength(16);
    expect(bands[0]).toEqual({ from: 0, to: 50 });
    expect(bands[15]).toEqual({ from: 750, to: 800 });
    const holders = (value: number) =>
      bands
        .filter((band, i) => inBand(value, band, i === bands.length - 1))
        .map((b) => b.from);
    expect(holders(40)).toEqual([0]);
    expect(holders(100)).toEqual([100]);
    expect(holders(800)).toEqual([750]);
  });
});
