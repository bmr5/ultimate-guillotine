/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { BoardClient } from "./fetchers";
import {
  fetchFinalRosters,
  fetchLatestSeason,
  fetchMembers,
  fetchNflState,
  fetchPlayerProjections,
  fetchPlayers,
  fetchRosterHoldings,
  fetchSeasonByYear,
  fetchTeams,
  fetchTeamSeasonState,
  fetchTeamWeekProjections,
  fetchWeeklyResults,
  IN_CHUNK_SIZE,
} from "./fetchers";

interface Call {
  table: string;
  columns: string;
  filters: [string, unknown][];
  /** `[column, ascending]` for the one fetcher that orders; undefined for the rest. */
  order?: [string, boolean];
  limit?: number;
}

/** A fixed row set, or one derived from the filters that call asked for. */
type FakeResponse = unknown[] | ((call: Call) => unknown[]);

function createFakeClient(
  responses: Record<string, FakeResponse>,
  errors: Record<string, string> = {},
): { client: BoardClient; calls: Call[] } {
  const calls: Call[] = [];
  const client = {
    from(table: string) {
      const call: Call = { table, columns: "", filters: [] };
      calls.push(call);
      const builder = {
        select(columns: string) {
          call.columns = columns;
          return builder;
        },
        eq(column: string, value: unknown) {
          call.filters.push([column, value]);
          return builder;
        },
        in(column: string, values: unknown[]) {
          call.filters.push([column, values]);
          return builder;
        },
        order(column: string, options: { ascending: boolean }) {
          call.order = [column, options.ascending];
          return builder;
        },
        limit(count: number) {
          call.limit = count;
          return builder;
        },
        then(resolve: (value: unknown) => unknown) {
          const message = errors[table];
          const response = responses[table];
          const data =
            typeof response === "function" ? response(call) : response ?? [];
          return Promise.resolve(
            message === undefined
              ? { data, error: null }
              : { data: null, error: { message } },
          ).then(resolve);
        },
      };
      return builder;
    },
  } as unknown as BoardClient;
  return { client, calls };
}

describe("fetchNflState", () => {
  it("reads the single pinned row", async () => {
    const { client, calls } = createFakeClient({
      nfl_state: [
        {
          id: 1,
          season: 2026,
          season_type: "regular",
          week: 3,
          display_week: 3,
          synced_at: "t",
        },
      ],
    });
    const state = await fetchNflState(client);
    expect(state?.week).toBe(3);
    expect(calls[0].table).toBe("nfl_state");
    expect(calls[0].columns).toBe(
      "id, season, season_type, week, display_week, synced_at",
    );
    expect(calls[0].filters).toEqual([["id", 1]]);
  });

  it("returns null when the row is missing", async () => {
    const { client } = createFakeClient({ nfl_state: [] });
    expect(await fetchNflState(client)).toBeNull();
  });

  it("throws a labelled error", async () => {
    const { client } = createFakeClient({}, { nfl_state: "boom" });
    await expect(fetchNflState(client)).rejects.toThrow("nfl_state: boom");
  });
});

describe("season and team fetchers", () => {
  it("finds the season by the nfl_state year", async () => {
    const { client, calls } = createFakeClient({
      seasons: [
        {
          id: 1,
          year: 2026,
          sleeper_league_id: "x",
          phase: "regular",
          expected_rosters: 18,
          waiver_budget: 100,
          roster_positions: [],
          league_synced_at: "t",
        },
      ],
    });
    const season = await fetchSeasonByYear(client, 2026);
    expect(season?.id).toBe(1);
    expect(calls[0].filters).toEqual([["year", 2026]]);
  });

  it("falls back to the newest season row when the nfl year has none", async () => {
    // The offseason shape: nfl_state has rolled to a year this league has no seasons row for.
    const { client, calls } = createFakeClient({
      seasons: [
        {
          id: 1,
          year: 2026,
          sleeper_league_id: "x",
          phase: "complete",
          expected_rosters: 18,
          waiver_budget: 100,
          roster_positions: [],
          league_synced_at: "t",
        },
      ],
    });
    const season = await fetchLatestSeason(client);
    expect(season?.year).toBe(2026);
    expect(calls[0].table).toBe("seasons");
    // No year filter at all — newest first, one row.
    expect(calls[0].filters).toEqual([]);
    expect(calls[0].order).toEqual(["year", false]);
    expect(calls[0].limit).toBe(1);
  });

  it("has no season to fall back to when the table is empty", async () => {
    const { client } = createFakeClient({ seasons: [] });
    expect(await fetchLatestSeason(client)).toBeNull();
  });

  it("reads teams for the season", async () => {
    const { client, calls } = createFakeClient({ teams: [] });
    await fetchTeams(client, 1);
    expect(calls[0].table).toBe("teams");
    expect(calls[0].columns).toBe(
      "id, sleeper_roster_id, team_name, member_id",
    );
    expect(calls[0].filters).toEqual([["season_id", 1]]);
  });

  it("reads only the two public label columns on members, never display_name", async () => {
    const { client, calls } = createFakeClient({ members: [] });
    await fetchMembers(client);
    expect(calls[0].columns).toBe("id, sleeper_display_name, nickname");
    // Column-wise, not substring-wise: `sleeper_display_name` contains "display_name".
    expect(calls[0].columns.split(", ")).not.toContain("display_name");
    expect(calls[0].filters).toEqual([]);
  });
});

describe("state, projection and roster fetchers", () => {
  it("reads team_season_state for the season", async () => {
    const { client, calls } = createFakeClient({ team_season_state: [] });
    await fetchTeamSeasonState(client, 1);
    expect(calls[0].columns).toContain("faab_remaining");
    expect(calls[0].columns).toContain("eliminated_week");
    expect(calls[0].filters).toEqual([["season_id", 1]]);
  });

  it("reads team_week_projections for the season and week", async () => {
    const { client, calls } = createFakeClient({ team_week_projections: [] });
    await fetchTeamWeekProjections(client, 1, 3);
    expect(calls[0].columns).toContain("coverage_pct");
    expect(calls[0].columns).toContain("is_provisional");
    expect(calls[0].filters).toEqual([
      ["season_id", 1],
      ["week", 3],
    ]);
  });

  it("reads roster_holdings for the season", async () => {
    const { client, calls } = createFakeClient({ roster_holdings: [] });
    await fetchRosterHoldings(client, 1);
    expect(calls[0].columns).toBe(
      "team_id, sleeper_player_id, slot, slot_index, lineup_position",
    );
    expect(calls[0].filters).toEqual([["season_id", 1]]);
  });

  it("reads weekly_results for the season", async () => {
    const { client, calls } = createFakeClient({ weekly_results: [] });
    await fetchWeeklyResults(client, 1);
    expect(calls[0].columns).toBe(
      "week, team_id, points, is_final, state_version",
    );
    expect(calls[0].filters).toEqual([["season_id", 1]]);
  });

  it("reads the frozen final rosters for the season", async () => {
    const { client, calls } = createFakeClient({ final_rosters: [] });
    await fetchFinalRosters(client, 1);
    expect(calls[0].table).toBe("final_rosters");
    expect(calls[0].columns).toBe(
      "team_id, eliminated_week, holdings, frozen_at",
    );
    expect(calls[0].filters).toEqual([["season_id", 1]]);
  });
});

describe("bulk player fetchers", () => {
  it("fetches every held player in one request", async () => {
    const { client, calls } = createFakeClient({ players: [] });
    await fetchPlayers(client, ["4046", "9999"]);
    expect(calls).toHaveLength(1);
    expect(calls[0].columns).toBe(
      // `injury_status` rides along on the same request: the card has to tell an injured
      // starter from a starter Sleeper simply has no number for.
      "sleeper_player_id, full_name, position, team, injury_status",
    );
    expect(calls[0].filters).toEqual([["sleeper_player_id", ["4046", "9999"]]]);
  });

  it("fetches every held player's projection in one request", async () => {
    const { client, calls } = createFakeClient({ player_projections: [] });
    await fetchPlayerProjections(client, 2026, 3, ["4046"]);
    expect(calls).toHaveLength(1);
    expect(calls[0].columns).toBe("sleeper_player_id, league_points");
    expect(calls[0].filters).toEqual([
      ["season", 2026],
      ["week", 3],
      ["sleeper_player_id", ["4046"]],
    ]);
  });

  it("chunks a large id list and merges the batches in id order", async () => {
    const ids = Array.from({ length: 400 }, (_, index) => `p${index}`);
    const { client, calls } = createFakeClient({
      players: (call) =>
        (call.filters[0][1] as string[]).map((id) => ({
          sleeper_player_id: id,
          full_name: `Player ${id}`,
          position: "QB",
          team: "BUF",
          injury_status: null,
        })),
    });
    const rows = await fetchPlayers(client, ids);
    // 400 ids in a single `.in()` is a query string long enough to be refused; three batches
    // are not.
    expect(calls).toHaveLength(3);
    expect(
      calls.map((call) => (call.filters[0][1] as string[]).length),
    ).toEqual([IN_CHUNK_SIZE, IN_CHUNK_SIZE, 400 - 2 * IN_CHUNK_SIZE]);
    expect(rows.map((row) => row.sleeper_player_id)).toEqual(ids);
  });

  it("chunks the projection id list too, keeping season and week on every batch", async () => {
    const ids = Array.from({ length: 400 }, (_, index) => `p${index}`);
    const { client, calls } = createFakeClient({
      player_projections: (call) =>
        (call.filters[2][1] as string[]).map((id) => ({
          sleeper_player_id: id,
          league_points: 1,
        })),
    });
    const rows = await fetchPlayerProjections(client, 2026, 3, ids);
    expect(calls).toHaveLength(3);
    for (const call of calls) {
      expect(call.filters[0]).toEqual(["season", 2026]);
      expect(call.filters[1]).toEqual(["week", 3]);
    }
    expect(
      calls.map((call) => (call.filters[2][1] as string[]).length),
    ).toEqual([IN_CHUNK_SIZE, IN_CHUNK_SIZE, 400 - 2 * IN_CHUNK_SIZE]);
    expect(rows.map((row) => row.sleeper_player_id)).toEqual(ids);
  });

  it("skips the request entirely when nothing is held", async () => {
    const { client, calls } = createFakeClient({ players: [] });
    expect(await fetchPlayers(client, [])).toEqual([]);
    expect(await fetchPlayerProjections(client, 2026, 3, [])).toEqual([]);
    expect(calls).toHaveLength(0);
  });
});
