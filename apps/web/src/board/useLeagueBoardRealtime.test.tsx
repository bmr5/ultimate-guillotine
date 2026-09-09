import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { boardKeys } from "./queryKeys";
import type { BoardRealtimeTable } from "./realtime";
import { REALTIME_MAX_WAIT_MS } from "./realtime";
import type { FakeableChannel, RealtimeTransport } from "./useLeagueBoardRealtime";
import { useLeagueBoardRealtime } from "./useLeagueBoardRealtime";

function createFakeTransport() {
  const handlers = new Map<string, () => void>();
  let statusHandler: ((status: string) => void) | null = null;
  const removeChannel = vi.fn();
  const channelNames: string[] = [];

  const channel: FakeableChannel = {
    on(_event, filter, handler) {
      handlers.set(filter.table, handler);
      return channel;
    },
    subscribe(handler) {
      statusHandler = handler;
      return channel;
    },
  };

  const transport: RealtimeTransport = {
    channel: (name) => {
      channelNames.push(name);
      return channel;
    },
    removeChannel,
  };

  return {
    transport,
    removeChannel,
    emit: (table: string) => handlers.get(table)?.(),
    setStatus: (status: string) => statusHandler?.(status),
    channelCount: () => channelNames.length,
    channelNames: () => [...channelNames],
    subscribedTables: () => [...handlers.keys()],
  };
}

function wrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("useLeagueBoardRealtime", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.useFakeTimers();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    queryClient.clear();
  });

  function mount(fake: ReturnType<typeof createFakeTransport>) {
    return renderHook(
      () =>
        useLeagueBoardRealtime({
          seasonId: 1,
          season: 2026,
          week: 3,
          transport: fake.transport,
        }),
      { wrapper: wrapper(queryClient) },
    );
  }

  it("subscribes one channel to every published table", () => {
    const fake = createFakeTransport();
    mount(fake);

    expect(fake.channelCount()).toBe(1);
    expect(fake.subscribedTables()).toEqual([
      "roster_holdings",
      "team_season_state",
      "team_week_projections",
      "nfl_state",
    ]);
  });

  it("does not refetch on the first connect, since the board just loaded", () => {
    const fake = createFakeTransport();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue();

    mount(fake);
    act(() => {
      fake.setStatus("SUBSCRIBED");
    });

    expect(invalidate).not.toHaveBeenCalled();
  });

  const TABLE_CASES: {
    table: BoardRealtimeTable;
    expected: readonly (readonly unknown[])[];
  }[] = [
    {
      table: "roster_holdings",
      expected: [
        boardKeys.rosterHoldings(1),
        ["board", "players", 1],
        ["board", "player_projections", 2026, 3],
      ],
    },
    {
      table: "team_season_state",
      expected: [boardKeys.teamSeasonState(1), boardKeys.finalRosters(1)],
    },
    {
      table: "team_week_projections",
      expected: [boardKeys.teamWeekProjections(1, 3)],
    },
    { table: "nfl_state", expected: [boardKeys.all] },
  ];

  it.each(TABLE_CASES)(
    "invalidates the $table keys after the debounce",
    ({ table, expected }) => {
      const fake = createFakeTransport();
      const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue();

      mount(fake);
      act(() => {
        fake.setStatus("SUBSCRIBED");
      });
      invalidate.mockClear();

      act(() => {
        fake.emit(table);
        vi.advanceTimersByTime(750);
      });

      expect(invalidate).toHaveBeenCalledTimes(expected.length);
      for (const queryKey of expected) {
        expect(invalidate).toHaveBeenCalledWith({ queryKey });
      }
    },
  );

  it("collapses a burst on one table into a single invalidation after the debounce", () => {
    const fake = createFakeTransport();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue();

    mount(fake);

    act(() => {
      fake.setStatus("SUBSCRIBED");
    });
    invalidate.mockClear();

    act(() => {
      fake.emit("team_week_projections");
      fake.emit("team_week_projections");
      fake.emit("team_week_projections");
    });
    expect(invalidate).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(750);
    });
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: boardKeys.teamWeekProjections(1, 3),
    });
  });

  it("invalidates each affected key once per burst", () => {
    const fake = createFakeTransport();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue();

    mount(fake);

    act(() => {
      fake.setStatus("SUBSCRIBED");
    });
    invalidate.mockClear();

    act(() => {
      fake.emit("team_season_state");
      fake.emit("team_week_projections");
      fake.emit("team_season_state");
      vi.advanceTimersByTime(750);
    });

    expect(invalidate).toHaveBeenCalledTimes(3);
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: boardKeys.teamSeasonState(1),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: boardKeys.finalRosters(1),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: boardKeys.teamWeekProjections(1, 3),
    });
  });

  it("flushes at the max wait when events keep resetting the debounce", () => {
    const fake = createFakeTransport();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue();

    mount(fake);
    act(() => {
      fake.setStatus("SUBSCRIBED");
    });
    invalidate.mockClear();

    // 500 ms apart, so the 750 ms trailing debounce never elapses on its own.
    act(() => {
      for (let elapsed = 0; elapsed < REALTIME_MAX_WAIT_MS; elapsed += 500) {
        fake.emit("team_week_projections");
        vi.advanceTimersByTime(500);
      }
    });

    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: boardKeys.teamWeekProjections(1, 3),
    });
  });

  it("collapses to one whole-board refetch past the eighteen-event ceiling", () => {
    const fake = createFakeTransport();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue();

    mount(fake);

    act(() => {
      fake.setStatus("SUBSCRIBED");
    });
    invalidate.mockClear();

    act(() => {
      for (let index = 0; index < 25; index += 1) {
        fake.emit("roster_holdings");
      }
      vi.advanceTimersByTime(750);
    });

    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: boardKeys.all });
  });

  it("reports the connection state and refetches everything on reconnect", () => {
    const fake = createFakeTransport();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue();

    const { result } = mount(fake);

    expect(result.current.isConnected).toBe(false);

    act(() => {
      fake.setStatus("SUBSCRIBED");
    });
    expect(result.current.isConnected).toBe(true);

    act(() => {
      fake.setStatus("CHANNEL_ERROR");
    });
    expect(result.current.isConnected).toBe(false);
    expect(result.current.reconnectAttempts).toBe(0);

    invalidate.mockClear();
    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    expect(fake.channelCount()).toBe(2);
    expect(fake.removeChannel).toHaveBeenCalledTimes(1);
    expect(result.current.reconnectAttempts).toBe(1);

    act(() => {
      fake.setStatus("SUBSCRIBED");
    });
    // Changes during the gap were missed, so everything refetches.
    expect(invalidate).toHaveBeenCalledWith({ queryKey: boardKeys.all });
    expect(result.current.reconnectAttempts).toBe(0);
    // The successful subscribe must not itself rebuild the channel.
    expect(fake.channelCount()).toBe(2);
  });

  it("backs off further on each failed attempt", () => {
    const fake = createFakeTransport();
    const { result } = mount(fake);

    act(() => {
      fake.setStatus("SUBSCRIBED");
      fake.setStatus("CHANNEL_ERROR");
      vi.advanceTimersByTime(1_000);
    });
    expect(result.current.reconnectAttempts).toBe(1);

    act(() => {
      fake.setStatus("TIMED_OUT");
      vi.advanceTimersByTime(1_999);
    });
    expect(result.current.reconnectAttempts).toBe(1);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.reconnectAttempts).toBe(2);
    expect(fake.channelCount()).toBe(3);
    expect(fake.channelNames()).toEqual([
      "league-board-0",
      "league-board-1",
      "league-board-2",
    ]);
  });

  it("notifies the caller when the connection state changes", () => {
    const fake = createFakeTransport();
    const onConnectionChange = vi.fn();

    renderHook(
      () =>
        useLeagueBoardRealtime({
          seasonId: 1,
          season: 2026,
          week: 3,
          transport: fake.transport,
          onConnectionChange,
        }),
      { wrapper: wrapper(queryClient) },
    );

    act(() => {
      fake.setStatus("SUBSCRIBED");
    });
    expect(onConnectionChange).toHaveBeenCalledWith(true);

    act(() => {
      fake.setStatus("CLOSED");
    });
    expect(onConnectionChange).toHaveBeenLastCalledWith(false);
  });

  it("refreshNow invalidates the whole board", () => {
    const fake = createFakeTransport();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue();
    const { result } = mount(fake);

    act(() => {
      result.current.refreshNow();
    });

    expect(invalidate).toHaveBeenCalledWith({ queryKey: boardKeys.all });
  });

  it("removes the channel on unmount", () => {
    const fake = createFakeTransport();
    const { unmount } = mount(fake);

    unmount();
    expect(fake.removeChannel).toHaveBeenCalled();
  });

  it("drops a pending flush when the hook unmounts", () => {
    const fake = createFakeTransport();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue();
    const { unmount } = mount(fake);

    act(() => {
      fake.setStatus("SUBSCRIBED");
      fake.emit("team_week_projections");
    });
    invalidate.mockClear();
    unmount();

    act(() => {
      vi.advanceTimersByTime(REALTIME_MAX_WAIT_MS);
    });
    expect(invalidate).not.toHaveBeenCalled();
  });
});
