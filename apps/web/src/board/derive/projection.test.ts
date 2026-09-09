/**
 * The caveat rule is arithmetic over plain numbers, so it runs under node like the other
 * derive modules.
 *
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import {
  COVERAGE_GATE_PCT,
  PARTIAL_COVERAGE_LABEL,
  PROJECTION_UNAVAILABLE_LABEL,
  PROJECTION_UNAVAILABLE_TEXT,
  resolveProjectionDisplay,
  STRICT_COVERAGE_GATE,
  type ProjectionDisplay,
  type ProjectionInput,
} from "./projection";

describe("resolveProjectionDisplay", () => {
  it("shows the bare number at or above the 95 percent gate", () => {
    expect(
      resolveProjectionDisplay({
        projectedPoints: 112.44,
        coveragePct: 100,
        isProvisional: false,
      }),
    ).toEqual({
      kind: "value",
      points: 112.44,
      text: "112.4",
      caveat: null,
      caveatLabel: null,
    });
  });

  it("shows the number with a partial caveat between zero and the gate", () => {
    const display = resolveProjectionDisplay({
      projectedPoints: 80,
      coveragePct: 66.67,
      isProvisional: true,
    });
    expect(display.kind).toBe("value");
    expect(display.text).toBe("80.0");
    expect(display.caveat).toBe("partial");
    expect(display.caveatLabel).toBe("Partial projection coverage");
  });

  it("shows an em dash when coverage is zero", () => {
    expect(
      resolveProjectionDisplay({
        projectedPoints: 0,
        coveragePct: 0,
        isProvisional: true,
      }),
    ).toEqual({
      kind: "unavailable",
      points: null,
      text: "—",
      caveat: "unavailable",
      caveatLabel: "Projection unavailable",
    });
  });

  it("shows an em dash when there is no projection row at all", () => {
    const display = resolveProjectionDisplay({
      projectedPoints: null,
      coveragePct: null,
      isProvisional: true,
    });
    expect(display.kind).toBe("unavailable");
    expect(display.points).toBeNull();
  });

  it("never renders a missing projection as zero", () => {
    const display = resolveProjectionDisplay({
      projectedPoints: null,
      coveragePct: null,
      isProvisional: true,
    });
    expect(display.text).not.toBe("0.0");
    expect(display.text).toBe("—");
  });

  it("treats a below-gate coverage figure as partial even if the flag lags", () => {
    const display = resolveProjectionDisplay({
      projectedPoints: 70,
      coveragePct: 94.9,
      isProvisional: false,
    });
    expect(display.caveat).toBe("partial");
  });
});

const value = (
  points: number,
  text: string,
  partial: boolean,
): ProjectionDisplay => ({
  kind: "value",
  points,
  text,
  caveat: partial ? "partial" : null,
  caveatLabel: partial ? PARTIAL_COVERAGE_LABEL : null,
});

const unavailable: ProjectionDisplay = {
  kind: "unavailable",
  points: null,
  text: PROJECTION_UNAVAILABLE_TEXT,
  caveat: "unavailable",
  caveatLabel: PROJECTION_UNAVAILABLE_LABEL,
};

interface ProjectionCase {
  name: string;
  input: ProjectionInput;
  strict?: boolean;
  expected: ProjectionDisplay;
}

const cases: ProjectionCase[] = [
  {
    name: "exactly at the gate is not partial",
    input: {
      projectedPoints: 101,
      coveragePct: COVERAGE_GATE_PCT,
      isProvisional: false,
    },
    expected: value(101, "101.0", false),
  },
  {
    name: "a hair under the gate is partial",
    input: {
      projectedPoints: 101,
      coveragePct: COVERAGE_GATE_PCT - 0.01,
      isProvisional: false,
    },
    expected: value(101, "101.0", true),
  },
  {
    name: "the provisional flag alone is enough to caveat full coverage",
    input: { projectedPoints: 99.95, coveragePct: 100, isProvisional: true },
    expected: value(99.95, "100.0", true),
  },
  {
    name: "a null coverage figure with points present is unavailable",
    input: { projectedPoints: 88, coveragePct: null, isProvisional: false },
    expected: unavailable,
  },
  {
    name: "null points with full coverage is unavailable, never zero",
    input: { projectedPoints: null, coveragePct: 100, isProvisional: false },
    expected: unavailable,
  },
  {
    name: "a negative coverage figure is unavailable",
    input: { projectedPoints: 12, coveragePct: -1, isProvisional: true },
    expected: unavailable,
  },
  {
    name: "a real zero projection above the gate still renders as zero points",
    input: { projectedPoints: 0, coveragePct: 100, isProvisional: false },
    expected: value(0, "0.0", false),
  },
  {
    name: "strict mode replaces the partial badge with the unavailable wording",
    input: { projectedPoints: 80, coveragePct: 66.67, isProvisional: true },
    strict: true,
    expected: unavailable,
  },
  {
    name: "strict mode leaves an at-gate projection alone",
    input: { projectedPoints: 80, coveragePct: 100, isProvisional: false },
    strict: true,
    expected: value(80, "80.0", false),
  },
];

describe.each(cases)(
  "resolveProjectionDisplay table: $name",
  ({ input, strict, expected }) => {
    it("resolves to the expected display", () => {
      expect(resolveProjectionDisplay(input, strict)).toEqual(expected);
    });

    it("does not mutate its input", () => {
      const snapshot = { ...input };
      resolveProjectionDisplay(input, strict);
      expect(input).toEqual(snapshot);
    });
  },
);

describe("projection constants", () => {
  it("keeps the gate and labels named rather than inline", () => {
    expect(COVERAGE_GATE_PCT).toBe(95);
    expect(PROJECTION_UNAVAILABLE_TEXT).toBe("—");
    expect(PARTIAL_COVERAGE_LABEL).toBe("Partial projection coverage");
    expect(PROJECTION_UNAVAILABLE_LABEL).toBe("Projection unavailable");
  });

  it("defaults the strict caveat wording to off", () => {
    expect(STRICT_COVERAGE_GATE).toBe(false);
  });
});
