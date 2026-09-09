import { describe, expect, it } from "vitest";

import {
  DEFAULT_POSITION_SORT_MODE,
  DEFAULT_SORT_MODE,
  parsePositionFilter,
  parsePositionSortMode,
  parseSortMode,
  POSITION_FILTERS,
  SORT_MODE_LABELS,
  SORT_MODES,
  type TableRow,
} from "./types";

describe("Database row types", () => {
  it("names every column the board reads on team_week_projections", () => {
    const row: TableRow<"team_week_projections"> = {
      season_id: 1,
      team_id: 7,
      week: 3,
      projected_points: 112.4,
      starter_slots: 9,
      filled_slots: 9,
      empty_slots: 0,
      starters_projected: 9,
      missing_projections: 0,
      coverage_pct: 100,
      is_provisional: false,
      computed_at: "2026-09-09T12:00:00Z",
    };
    expect(row.is_provisional).toBe(false);
    expect(row.coverage_pct).toBe(100);
  });

  it("names every column the board reads on team_season_state", () => {
    const row: TableRow<"team_season_state"> = {
      season_id: 1,
      team_id: 7,
      faab_budget: 100,
      faab_used: 25,
      faab_remaining: 75,
      points_for: 301.5,
      points_against: 288.25,
      is_eliminated: false,
      eliminated_week: null,
      elimination_source: null,
      state_version: 1,
      synced_at: "2026-09-09T12:00:00Z",
    };
    expect(row.faab_remaining).toBe(75);
  });

  it("names every column the board reads on roster_holdings", () => {
    const row: TableRow<"roster_holdings"> = {
      season_id: 1,
      team_id: 7,
      sleeper_player_id: "4046",
      slot: "starter",
      slot_index: 0,
      lineup_position: "QB",
      synced_at: "2026-09-09T12:00:00Z",
    };
    expect(row.slot).toBe("starter");
  });

  it("carries both public label columns on members", () => {
    const row: TableRow<"members"> = {
      id: 3,
      display_name: "legacy_username",
      sleeper_display_name: "Legacy Owner",
      nickname: "Ben",
    };
    // display_name is typed because the column exists, but no fetcher ever selects it.
    expect(row.nickname).toBe("Ben");
    expect(row.sleeper_display_name).toBe("Legacy Owner");
  });

  it("names every column the board reads on final_rosters", () => {
    const row: TableRow<"final_rosters"> = {
      season_id: 1,
      team_id: 7,
      eliminated_week: 4,
      holdings: [
        {
          sleeper_player_id: "4046",
          slot: "starter",
          slot_index: 0,
          lineup_position: "QB",
        },
      ],
      frozen_at: "2026-10-01T05:00:00Z",
    };
    expect(row.holdings[0].sleeper_player_id).toBe("4046");
    expect(row.eliminated_week).toBe(4);
  });

  it("types every numeric column as a JS number, never a string", () => {
    // PostgREST serialises the row with postgres `to_json`, and `to_json(numeric)` emits
    // an unquoted JSON literal, so supabase-js hands the board numbers. This is the wire
    // shape every later derivation and sort comparator depends on.
    const wire = JSON.parse(
      '{"points_for":301.50,"coverage_pct":88.75,"league_points":17.30}',
    ) as Pick<TableRow<"team_season_state">, "points_for"> &
      Pick<TableRow<"team_week_projections">, "coverage_pct"> &
      Pick<TableRow<"player_projections">, "league_points">;

    expect(typeof wire.points_for).toBe("number");
    expect(wire.points_for).toBe(301.5);
    expect(typeof wire.coverage_pct).toBe("number");
    expect(wire.league_points).toBe(17.3);

    // @ts-expect-error a numeric column is never the string form some PostgREST setups emit.
    const stringForm: TableRow<"team_season_state">["points_for"] = "301.50";
    expect(stringForm).toBe("301.50");
  });
});

describe("parseSortMode", () => {
  it("accepts every supported mode", () => {
    expect(parseSortMode("projection")).toBe("projection");
    expect(parseSortMode("faab")).toBe("faab");
    expect(parseSortMode("points_for")).toBe("points_for");
  });

  it("falls back to the default for anything else", () => {
    expect(parseSortMode("bogus")).toBe(DEFAULT_SORT_MODE);
    expect(parseSortMode(null)).toBe("projection");
    expect(parseSortMode(undefined)).toBe("projection");
  });

  it("labels every mode", () => {
    expect(SORT_MODES.map((mode) => SORT_MODE_LABELS[mode])).toEqual([
      "Projection",
      "FAAB",
      "Total",
    ]);
  });
});

describe("parsePositionFilter", () => {
  it("accepts every position the quick view offers", () => {
    for (const position of POSITION_FILTERS) {
      expect(parsePositionFilter(position)).toBe(position);
    }
  });

  it("reads a shared link's lower-case spelling as the same position", () => {
    expect(parsePositionFilter("te")).toBe("TE");
    expect(parsePositionFilter(" def ")).toBe("DEF");
  });

  it("reads anything else as the whole board", () => {
    expect(parsePositionFilter(null)).toBeNull();
    expect(parsePositionFilter(undefined)).toBeNull();
    expect(parsePositionFilter("")).toBeNull();
    expect(parsePositionFilter("all")).toBeNull();
    expect(parsePositionFilter("LB")).toBeNull();
  });
});

describe("parsePositionSortMode", () => {
  it("keeps the two sorts a position view offers", () => {
    expect(parsePositionSortMode("faab")).toBe("faab");
    expect(parsePositionSortMode("projection")).toBe("projection");
  });

  it("falls back to FAAB for the board sorts a position view does not offer", () => {
    expect(parsePositionSortMode("points_for")).toBe(
      DEFAULT_POSITION_SORT_MODE,
    );
    expect(parsePositionSortMode(null)).toBe("faab");
  });
});
