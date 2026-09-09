/**
 * Pure aggregation over plain rows: no DOM, no timers.
 *
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import {
  summarizeWeeklyResults,
  type TeamPointsSummary,
  type WeeklyResultRow,
} from "./records";

const row = (over: Partial<WeeklyResultRow>): WeeklyResultRow => ({
  week: 1,
  team_id: 1,
  points: 100,
  is_final: true,
  state_version: 1,
  ...over,
});

describe("summarizeWeeklyResults", () => {
  it("sums points for across final weeks", () => {
    const summaries = summarizeWeeklyResults([
      row({ week: 1, team_id: 1, points: 101.25 }),
      row({ week: 2, team_id: 1, points: 98.5 }),
      row({ week: 1, team_id: 2, points: 88.1 }),
    ]);
    expect(summaries.get(1)).toEqual({
      pointsFor: 199.75,
      weeksScored: 2,
      lastFinalWeek: 2,
    });
    expect(summaries.get(2)?.pointsFor).toBe(88.1);
  });

  it("keeps only the highest state_version for a team-week", () => {
    const summaries = summarizeWeeklyResults([
      row({ week: 1, team_id: 1, points: 90, state_version: 1 }),
      row({ week: 1, team_id: 1, points: 120, state_version: 2 }),
    ]);
    expect(summaries.get(1)?.pointsFor).toBe(120);
    expect(summaries.get(1)?.weeksScored).toBe(1);
  });

  it("ignores weeks that are not final", () => {
    const summaries = summarizeWeeklyResults([
      row({ week: 1, team_id: 1, points: 90, is_final: true }),
      row({ week: 2, team_id: 1, points: 60, is_final: false }),
    ]);
    expect(summaries.get(1)).toEqual({
      pointsFor: 90,
      weeksScored: 1,
      lastFinalWeek: 1,
    });
  });

  it("returns an empty map for no rows", () => {
    expect(summarizeWeeklyResults([]).size).toBe(0);
  });
});

interface RecordsCase {
  name: string;
  rows: WeeklyResultRow[];
  expected: Array<[number, TeamPointsSummary]>;
}

const cases: RecordsCase[] = [
  {
    name: "an out-of-order week list still reports the highest final week",
    rows: [
      row({ week: 3, points: 70 }),
      row({ week: 1, points: 80 }),
      row({ week: 2, points: 90 }),
    ],
    expected: [[1, { pointsFor: 240, weeksScored: 3, lastFinalWeek: 3 }]],
  },
  {
    name: "a lower state_version arriving last does not overwrite the newest row",
    rows: [
      row({ week: 1, points: 120, state_version: 2 }),
      row({ week: 1, points: 90, state_version: 1 }),
    ],
    expected: [[1, { pointsFor: 120, weeksScored: 1, lastFinalWeek: 1 }]],
  },
  {
    name: "a correction that reopens a week drops it from the summary",
    rows: [
      row({ week: 1, points: 90, is_final: true, state_version: 1 }),
      row({ week: 1, points: 90, is_final: false, state_version: 2 }),
      row({ week: 2, points: 55, is_final: true, state_version: 1 }),
    ],
    expected: [[1, { pointsFor: 55, weeksScored: 1, lastFinalWeek: 2 }]],
  },
  {
    name: "float sums stay at two decimals rather than drifting",
    rows: [row({ week: 1, points: 0.1 }), row({ week: 2, points: 0.2 })],
    expected: [[1, { pointsFor: 0.3, weeksScored: 2, lastFinalWeek: 2 }]],
  },
  {
    name: "teams are summarised independently",
    rows: [
      row({ team_id: 1, week: 1, points: 10 }),
      row({ team_id: 2, week: 1, points: 20 }),
      row({ team_id: 2, week: 2, points: 30, is_final: false }),
    ],
    expected: [
      [1, { pointsFor: 10, weeksScored: 1, lastFinalWeek: 1 }],
      [2, { pointsFor: 20, weeksScored: 1, lastFinalWeek: 1 }],
    ],
  },
  {
    name: "a team with only non-final weeks gets no summary at all",
    rows: [row({ week: 1, points: 40, is_final: false })],
    expected: [],
  },
];

describe.each(cases)(
  "summarizeWeeklyResults table: $name",
  ({ rows, expected }) => {
    it("produces the expected summaries", () => {
      const entries = [...summarizeWeeklyResults(rows).entries()].sort(
        ([left], [right]) => left - right,
      );
      expect(entries).toEqual(expected);
    });

    it("does not mutate the input rows", () => {
      const snapshot = structuredClone(rows);
      summarizeWeeklyResults(rows);
      expect(rows).toEqual(snapshot);
    });
  },
);
