import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./boardClient", () => ({ boardClient: {} }));
vi.mock("./fetchers", () => ({
  fetchFinalRosters: vi.fn(),
  fetchMembers: vi.fn(),
  fetchNflState: vi.fn(),
  fetchPlayerProjections: vi.fn(),
  fetchPlayers: vi.fn(),
  fetchRosterHoldings: vi.fn(),
  fetchSeasonByYear: vi.fn(),
  fetchTeamSeasonState: vi.fn(),
  fetchTeamWeekProjections: vi.fn(),
  fetchTeams: vi.fn(),
  fetchWeeklyResults: vi.fn(),
}));

import * as fetchers from "./fetchers";
import { boardKeys, fingerprintIds } from "./queryKeys";
import { useBoardData } from "./useBoardData";

const NFL_STATE = {
  id: 1,
  season: 2026,
  season_type: "regular",
  week: 3,
  display_week: 3,
  synced_at: "2026-09-09T00:00:00Z",
};

const SEASON = {
  id: 7,
  year: 2026,
  sleeper_league_id: "x",
  phase: "regular",
  expected_rosters: 18,
  waiver_budget: 100,
  roster_positions: [],
  league_synced_at: "2026-09-09T00:00:00Z",
};

const TEAM = {
  id: 11,
  sleeper_roster_id: 1,
  team_name: "Kneel Before Zod",
  member_id: 21,
};

function stubFetchers(): void {
  vi.mocked(fetchers.fetchNflState).mockResolvedValue(NFL_STATE);
  vi.mocked(fetchers.fetchSeasonByYear).mockResolvedValue(SEASON);
  vi.mocked(fetchers.fetchTeams).mockResolvedValue([TEAM]);
  vi.mocked(fetchers.fetchMembers).mockResolvedValue([]);
  vi.mocked(fetchers.fetchTeamSeasonState).mockResolvedValue([]);
  vi.mocked(fetchers.fetchTeamWeekProjections).mockResolvedValue([]);
  vi.mocked(fetchers.fetchRosterHoldings).mockResolvedValue([]);
  vi.mocked(fetchers.fetchWeeklyResults).mockResolvedValue([]);
  vi.mocked(fetchers.fetchFinalRosters).mockResolvedValue([]);
  vi.mocked(fetchers.fetchPlayers).mockResolvedValue([]);
  vi.mocked(fetchers.fetchPlayerProjections).mockResolvedValue([]);
}

function renderBoardData() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const view = renderHook(() => useBoardData({ pollingMs: false }), { wrapper });
  return { ...view, queryClient };
}

beforeEach(() => {
  stubFetchers();
});

describe("useBoardData", () => {
  it("resolves the season and week from nfl_state", async () => {
    const { result } = renderBoardData();
    await waitFor(() => {
      expect(result.current.teams).toHaveLength(1);
    });
    expect(result.current.season).toBe(2026);
    expect(result.current.week).toBe(3);
    expect(result.current.seasonId).toBe(7);
    expect(vi.mocked(fetchers.fetchTeams).mock.calls[0][1]).toBe(7);
    expect(vi.mocked(fetchers.fetchTeamWeekProjections).mock.calls[0].slice(1)).toEqual([
      7, 3,
    ]);
    expect(result.current.isPending).toBe(false);
    expect(result.current.isEmpty).toBe(false);
  });

  it("reaches the empty state when nfl_state has no row", async () => {
    vi.mocked(fetchers.fetchNflState).mockResolvedValue(null);
    const { result } = renderBoardData();
    // The downstream queries are disabled, never pending-then-resolved. A disabled query keeps
    // status "pending" forever, so the loading flag has to read isLoading, not isPending, or
    // the board spins instead of saying it has nothing to show.
    await waitFor(() => {
      expect(result.current.isPending).toBe(false);
    });
    expect(result.current.isEmpty).toBe(true);
    expect(result.current.teams).toEqual([]);
    expect(result.current.errors).toEqual([]);
    expect(vi.mocked(fetchers.fetchTeams)).not.toHaveBeenCalled();
  });

  it("asks for live holdings and frozen snapshot ids in one player request", async () => {
    vi.mocked(fetchers.fetchRosterHoldings).mockResolvedValue([
      {
        team_id: 11,
        sleeper_player_id: "4046",
        slot: "starter",
        slot_index: 0,
        lineup_position: "QB",
      },
    ]);
    vi.mocked(fetchers.fetchFinalRosters).mockResolvedValue([
      {
        team_id: 12,
        eliminated_week: 2,
        holdings: [
          {
            sleeper_player_id: "9999",
            slot: "bench",
            slot_index: null,
            lineup_position: null,
          },
        ],
        frozen_at: "2026-09-08T00:00:00Z",
      },
    ]);
    const { result, queryClient } = renderBoardData();
    await waitFor(() => {
      expect(vi.mocked(fetchers.fetchPlayers)).toHaveBeenCalled();
    });
    expect(vi.mocked(fetchers.fetchPlayers).mock.calls).toHaveLength(1);
    expect(vi.mocked(fetchers.fetchPlayers).mock.calls[0][1]).toEqual(["4046", "9999"]);
    expect(vi.mocked(fetchers.fetchPlayerProjections).mock.calls[0].slice(1)).toEqual([
      2026,
      3,
      ["4046", "9999"],
    ]);

    // Keyed on the ids, so a newly held or newly frozen player is a cache miss rather than a
    // stale directory that renders him as "Unknown player".
    const fingerprint = fingerprintIds(["4046", "9999"]);
    const keys = queryClient
      .getQueryCache()
      .getAll()
      .map((query) => query.queryKey);
    expect(keys).toContainEqual([...boardKeys.players(7, fingerprint)]);
    expect(keys).toContainEqual([
      ...boardKeys.playerProjections(2026, 3, fingerprint),
    ]);
    expect(result.current.errors).toEqual([]);
  });

  it("labels a failed query by its board section and keeps the rest", async () => {
    vi.mocked(fetchers.fetchTeams).mockRejectedValue(new Error("teams: boom"));
    const { result } = renderBoardData();
    await waitFor(() => {
      expect(result.current.errors).toHaveLength(1);
    });
    expect(result.current.errors[0]).toEqual({
      section: "Teams",
      message: "teams: boom",
    });
    // A failed teams query is not an empty board — the empty state would claim there are no
    // teams when the truth is that the request failed.
    expect(result.current.isEmpty).toBe(false);
  });

  it("reports the newest computed_at as the last projection pull", async () => {
    vi.mocked(fetchers.fetchTeamWeekProjections).mockResolvedValue([
      makeProjection(11, "2026-09-09T18:00:00Z"),
      makeProjection(12, "2026-09-09T19:30:00Z"),
      makeProjection(13, "not a date"),
    ]);
    const { result } = renderBoardData();
    await waitFor(() => {
      expect(result.current.projectionsUpdatedAt).not.toBeNull();
    });
    expect(result.current.projectionsUpdatedAt).toBe(
      Date.parse("2026-09-09T19:30:00Z"),
    );
  });

  it("has no projection pull time before any projection row arrives", async () => {
    const { result } = renderBoardData();
    await waitFor(() => {
      expect(result.current.isPending).toBe(false);
    });
    expect(result.current.projectionsUpdatedAt).toBeNull();
  });
});

function makeProjection(teamId: number, computedAt: string) {
  return {
    season_id: 7,
    team_id: teamId,
    week: 3,
    projected_points: 100,
    starter_slots: 9,
    filled_slots: 9,
    empty_slots: 0,
    starters_projected: 9,
    missing_projections: 0,
    coverage_pct: 100,
    is_provisional: false,
    computed_at: computedAt,
  };
}
