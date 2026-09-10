import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TradeCatalogRow } from "./fetchers";
import * as fetchers from "./fetchers";
import { historyKeys } from "./queryKeys";
import { useTradeCatalog } from "./useTradeCatalog";

vi.mock("@/board/boardClient", () => ({ boardClient: {} }));
vi.mock("./fetchers", () => ({
  fetchHistoryMembers: vi.fn(),
  fetchHistoryPlayers: vi.fn(),
  fetchRegisteredRevisions: vi.fn(),
  fetchRegisteredTrades: vi.fn(),
  fetchTradeCatalog: vi.fn(),
}));

function catalogRow(
  id: number,
  season: number,
  loadedAt: string,
): TradeCatalogRow {
  return {
    id,
    catalog_id: `c${id}`,
    season,
    week: 1,
    occurred_on: null,
    trade_type: "trade",
    structure: "1-for-1",
    party_member_ids: [1],
    party_count: 1,
    assets: [
      {
        kind: "player",
        sleeper_player_id: `p${id}`,
        name: "A Player",
        position: "RB",
      },
    ],
    confidence: "high",
    announcement: null,
    unresolved_parties: 0,
    loaded_at: loadedAt,
  };
}

/** A registered trade, whose player assets are the ones the directory has to name. */
const REGISTERED = {
  id: 5,
  created_at: "2026-09-09T21:12:00Z",
  announced_at: null,
  trade_code: "T-5",
  status: "accepted" as const,
  current_revision_id: 50,
  seasons: { year: 2026 },
};

const REVISION = {
  id: 50,
  announcement: null,
  trade_id: 5,
  effective_week: 2,
  kind: "trade",
  parties: [{ member_id: 1 }, { member_id: 2 }],
  assets: [
    { kind: "player", player_id: "9999", from_member_id: 1, to_member_id: 2 },
    { kind: "player", player_id: "4046", from_member_id: 2, to_member_id: 1 },
  ],
};

function stubFetchers(): void {
  vi.mocked(fetchers.fetchTradeCatalog).mockResolvedValue([]);
  vi.mocked(fetchers.fetchRegisteredTrades).mockResolvedValue([]);
  vi.mocked(fetchers.fetchRegisteredRevisions).mockResolvedValue([]);
  vi.mocked(fetchers.fetchHistoryMembers).mockResolvedValue([]);
  vi.mocked(fetchers.fetchHistoryPlayers).mockResolvedValue([]);
}

function renderCatalog() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { ...renderHook(() => useTradeCatalog(), { wrapper }), queryClient };
}

beforeEach(() => {
  stubFetchers();
});

describe("useTradeCatalog", () => {
  it("asks the directory only for the players the merged trades reference", async () => {
    vi.mocked(fetchers.fetchTradeCatalog).mockResolvedValue([
      catalogRow(1, 2024, "2026-09-09T12:00:00Z"),
    ]);
    vi.mocked(fetchers.fetchRegisteredTrades).mockResolvedValue([REGISTERED]);
    vi.mocked(fetchers.fetchRegisteredRevisions).mockResolvedValue([REVISION]);
    vi.mocked(fetchers.fetchHistoryPlayers).mockResolvedValue([
      { sleeper_player_id: "9999", full_name: "Puka Nacua", position: "WR" },
    ]);

    const { result, queryClient } = renderCatalog();
    await waitFor(() => {
      expect(vi.mocked(fetchers.fetchHistoryPlayers)).toHaveBeenCalled();
    });

    // Sorted and deduped, and only the *nameless* assets: the catalog row already carries its
    // analyst-written name, so `p1` is never requested.
    expect(vi.mocked(fetchers.fetchHistoryPlayers).mock.calls[0][1]).toEqual([
      "4046",
      "9999",
    ]);
    const keys = queryClient
      .getQueryCache()
      .getAll()
      .map((query) => query.queryKey);
    expect(keys).toContainEqual([...historyKeys.players(["9999", "4046"])]);

    await waitFor(() => {
      expect(result.current.isPending).toBe(false);
    });
    const registered = result.current.trades.find((trade) => trade.registered);
    expect(registered?.assets).toEqual([
      expect.objectContaining({ playerId: "9999", name: "Puka Nacua" }),
      // In the directory's response but not resolved: the id is unknown to `players`.
      expect.objectContaining({ playerId: "4046", name: "Unlisted player" }),
    ]);
    expect(result.current.errors).toEqual([]);
  });

  it("never opens a directory request when nothing needs naming", async () => {
    vi.mocked(fetchers.fetchTradeCatalog).mockResolvedValue([
      catalogRow(1, 2024, "2026-09-09T12:00:00Z"),
    ]);
    const { result } = renderCatalog();
    // The disabled directory query stays `pending` forever, so this is also the assertion that
    // a catalog-only league leaves the skeleton rather than spinning for good.
    await waitFor(() => {
      expect(result.current.isPending).toBe(false);
    });
    expect(vi.mocked(fetchers.fetchHistoryPlayers)).not.toHaveBeenCalled();
    expect(result.current.trades).toHaveLength(1);
  });

  it("names every failed source and keeps the others", async () => {
    vi.mocked(fetchers.fetchTradeCatalog).mockRejectedValue(
      new Error("trade_catalog: boom"),
    );
    vi.mocked(fetchers.fetchRegisteredRevisions).mockRejectedValue(
      new Error("trade_revisions: boom"),
    );
    vi.mocked(fetchers.fetchHistoryMembers).mockResolvedValue([
      { id: 1, sleeper_display_name: null, nickname: "Alpha" },
    ]);

    const { result } = renderCatalog();
    await waitFor(() => {
      expect(result.current.errors).toHaveLength(2);
    });
    expect(
      result.current.errors.map((entry) => [entry.source, entry.error.message]),
    ).toEqual([
      ["Trade catalog", "trade_catalog: boom"],
      ["Trade revisions", "trade_revisions: boom"],
    ]);
    // The members query succeeded, and a failure elsewhere does not throw its rows away.
    expect(result.current.members).toHaveLength(1);
  });

  it("stays pending while the revisions query is still in flight", async () => {
    let release: (rows: fetchers.RegisteredRevisionRow[]) => void = () => {};
    vi.mocked(fetchers.fetchRegisteredRevisions).mockImplementation(
      () =>
        new Promise<fetchers.RegisteredRevisionRow[]>((resolve) => {
          release = resolve;
        }),
    );
    vi.mocked(fetchers.fetchRegisteredTrades).mockResolvedValue([REGISTERED]);

    const { result } = renderCatalog();
    // Every other source has landed; a registered trade with no revision yet has no assets and
    // no week, so painting it now would fill those in a moment later.
    await waitFor(() => {
      expect(vi.mocked(fetchers.fetchRegisteredTrades)).toHaveBeenCalled();
    });
    expect(result.current.isPending).toBe(true);

    release([REVISION]);
    await waitFor(() => {
      expect(result.current.isPending).toBe(false);
    });
    expect(result.current.trades[0].week).toBe(2);
  });

  it("reports the newest catalog loaded_at, and none when the catalog is empty", async () => {
    vi.mocked(fetchers.fetchTradeCatalog).mockResolvedValue([
      catalogRow(1, 2024, "2026-09-08T12:00:00Z"),
      catalogRow(2, 2023, "2026-09-09T18:30:00Z"),
    ]);
    const { result } = renderCatalog();
    await waitFor(() => {
      expect(result.current.loadedAt).not.toBeNull();
    });
    // `loaded_at` is the catalog's own load stamp; the registered tables carry none, so the
    // line under the page is the catalog's newest reading and nothing else.
    expect(result.current.loadedAt).toBe(Date.parse("2026-09-09T18:30:00Z"));

    stubFetchers();
    const empty = renderCatalog();
    await waitFor(() => {
      expect(empty.result.current.isPending).toBe(false);
    });
    expect(empty.result.current.loadedAt).toBeNull();
  });

  it("counts the catalog rows a registered season replaced", async () => {
    vi.mocked(fetchers.fetchTradeCatalog).mockResolvedValue([
      catalogRow(1, 2026, "2026-09-09T12:00:00Z"),
      catalogRow(2, 2024, "2026-09-09T12:00:00Z"),
    ]);
    vi.mocked(fetchers.fetchRegisteredTrades).mockResolvedValue([REGISTERED]);
    vi.mocked(fetchers.fetchRegisteredRevisions).mockResolvedValue([REVISION]);

    const { result } = renderCatalog();
    await waitFor(() => {
      expect(result.current.replacedByBackfill).toBe(1);
    });
    expect(result.current.trades.map((trade) => trade.season)).toEqual([
      2026, 2024,
    ]);
  });
});
