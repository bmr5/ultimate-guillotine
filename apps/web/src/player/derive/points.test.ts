/** @vitest-environment node */
import { describe, expect, it } from "vitest";

import type { SeasonScoreRow } from "../fetchers";
import { rosteredWeeksCaption, seasonPoints } from "./points";

const rows: SeasonScoreRow[] = [
  { week: 1, team_id: 7, players_points: { "9493": 12.4, "4046": 20.1 } },
  { week: 2, team_id: 7, players_points: { "9493": 0 } },
  { week: 3, team_id: 9, players_points: { "9493": 7.5 } },
  // The same player named twice in one week: counted once.
  { week: 3, team_id: 7, players_points: { "9493": 7.5 } },
  { week: 4, team_id: 7, players_points: { "4046": 3 } },
];

describe("seasonPoints", () => {
  it("sums the weeks the player was rostered and counts them", () => {
    expect(seasonPoints(rows, "9493")).toEqual({ total: 19.9, weeks: 3 });
  });

  it("is zero over no weeks for a player nobody has rostered", () => {
    expect(seasonPoints(rows, "0000")).toEqual({ total: 0, weeks: 0 });
  });

  it("drops a value that is not a finite number", () => {
    const junk: SeasonScoreRow[] = [
      { week: 1, team_id: 7, players_points: { "9493": Number.NaN } },
    ];
    expect(seasonPoints(junk, "9493")).toEqual({ total: 0, weeks: 0 });
  });
});

describe("rosteredWeeksCaption", () => {
  it("counts the weeks in words", () => {
    expect(rosteredWeeksCaption(1)).toBe("in 1 rostered week");
    expect(rosteredWeeksCaption(3)).toBe("in 3 rostered weeks");
  });
});
