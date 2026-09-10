import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SeasonResultRow } from "./fetchers";
import * as fetchers from "./fetchers";
import { useSeasonResults } from "./useSeasonResults";

vi.mock("@/board/boardClient", () => ({ boardClient: {} }));
vi.mock("./fetchers", () => ({
  fetchHistoryMembers: vi.fn(),
  fetchSeasonResults: vi.fn(),
}));

function seasonRow(eliminations: unknown): SeasonResultRow {
  return {
    id: 1,
    season: 2024,
    champion_member_id: 1,
    co_champion_member_id: null,
    runner_up_member_id: 99,
    third_member_id: null,
    team_count: 19,
    eliminations: eliminations as SeasonResultRow["eliminations"],
    notes: null,
    loaded_at: "2026-09-09T12:00:00Z",
  };
}

function renderSeasons() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return renderHook(() => useSeasonResults(), { wrapper });
}

beforeEach(() => {
  vi.mocked(fetchers.fetchSeasonResults).mockResolvedValue([]);
  vi.mocked(fetchers.fetchHistoryMembers).mockResolvedValue([
    { id: 1, nickname: "Alpha", sleeper_display_name: null },
  ]);
});

describe("useSeasonResults", () => {
  it("reads the two counts the loader writes and keeps a missing one null", async () => {
    // The shape `history/records.py` `_entry` actually writes: no `remaining` key has ever
    // existed, and 2023's rows carry a null `pool_out` because that season had no pool column.
    vi.mocked(fetchers.fetchSeasonResults).mockResolvedValue([
      seasonRow([
        { week: 11, order: 1, member_id: null, gulag_out: 4, pool_out: null },
        { week: 12, order: 2, member_id: null, gulag_out: 2, pool_out: 1 },
      ]),
    ]);
    const { result } = renderSeasons();
    await waitFor(() => expect(result.current.isPending).toBe(false));

    expect(result.current.seasons[0].eliminations).toEqual([
      { week: 11, order: 1, memberId: null, gulagOut: 4, poolOut: null },
      { week: 12, order: 2, memberId: null, gulagOut: 2, poolOut: 1 },
    ]);
  });

  it("skips a malformed elimination element rather than throwing on it", async () => {
    // `season_results.eliminations` is a JSON document, and nothing about the column forbids a
    // null inside its array. Reading `.week` off one would cost the whole page.
    vi.mocked(fetchers.fetchSeasonResults).mockResolvedValue([
      seasonRow([
        null,
        "week 12",
        { week: 13, order: 3, member_id: null, gulag_out: 1, pool_out: 0 },
      ]),
    ]);
    const { result } = renderSeasons();
    await waitFor(() => expect(result.current.isPending).toBe(false));

    // The surviving entry keeps the `order` the document gave it, not its position among the
    // survivors: the card keys on it.
    expect(result.current.seasons[0].eliminations).toEqual([
      { week: 13, order: 3, memberId: null, gulagOut: 1, poolOut: 0 },
    ]);
  });

  it("labels a member it knows and answers null for one it does not", async () => {
    vi.mocked(fetchers.fetchSeasonResults).mockResolvedValue([seasonRow([])]);
    const { result } = renderSeasons();
    await waitFor(() => expect(result.current.isPending).toBe(false));

    const season = result.current.seasons[0];
    expect(season.championLabel).toBe("Alpha");
    // Id 99 is nobody in `members`, and the card renders that as "Unlisted" — the hook does
    // not guess a label for it.
    expect(season.runnerUpLabel).toBeNull();
    expect(season.coChampionLabel).toBeNull();
  });

  it("names every failed source and keeps the others", async () => {
    vi.mocked(fetchers.fetchSeasonResults).mockRejectedValue(
      new Error("season_results: boom"),
    );
    const { result } = renderSeasons();
    await waitFor(() => expect(result.current.errors).toHaveLength(1));
    expect(result.current.errors[0].source).toBe("Season results");
  });
});
