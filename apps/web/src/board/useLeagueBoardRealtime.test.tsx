import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { boardKeys } from "./queryKeys";
import type { BoardRealtimeTable } from "./realtime";
import { REALTIME_MAX_WAIT_MS } from "./realtime";
import type {
  FakeableChannel,
  RealtimeTransport,
} from "./useLeagueBoardRealtime";
import { useLeagueBoardRealtime } from "./useLeagueBoardRealtime";

/**
 * A fresh object per `channel()` call, exactly as `supabase.channel` returns — so a test can
 * reach a channel the hook has already torn down and check that its callbacks are inert.
 */
interface FakeChannel extends FakeableChannel {
  name: string;
  handlers: Map<string, () => void>;
  statusHandler: ((status: string) => void) | null;
}

function createFakeTransport() {
  const channels: FakeChannel[] = [];
  const removeChannel = vi.fn();

  const transport: RealtimeTransport = {
    channel: (name) => {
      const created: FakeChannel = {
        name,
        handlers: new Map(),
        statusHandler: null,
        on(_event, filter, handler) {
          created.handlers.set(filter.table, handler);
          return created;
        },
        subscribe(handler) {
          created.statusHandler = handler;
          return created;
        },
      };
      channels.push(created);
      return created;
    },
    removeChannel,
  };

  const latest = () => channels.at(-1);

  return {
    transport,
    removeChannel,
    emit: (table: string) => latest()?.handlers.get(table)?.(),
    setStatus: (status: string) => latest()?.statusHandler?.(status),
    setStatusOn: (index: number, status: string) =>
      channels[index]?.statusHandler?.(status),
    channelCount: () => channels.length,
    channelNames: () => channels.map((channel) => channel.name),
    subscribedTables: () => [...(latest()?.handlers.keys() ?? [])],
  };
}

/** The midpoint of the jitter range, so a backoff lands on exactly its undithered delay. */
const NO_JITTER = () => 0.5;

function wrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
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
          random: NO_JITTER,
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
    const invalidate = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue();

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
      // Not the player directory: its key already carries a fingerprint of the held ids.
      expected: [
        boardKeys.rosterHoldings(1),
        boardKeys.playerProjectionsPrefix(2026, 3),
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
    // The heartbeat rewrites nfl_state without moving the week, so this stays on its own key;
    // a real rollover re-keys every dependent query by itself.
    { table: "nfl_state", expected: [boardKeys.nflState()] },
  ];

  it.each(TABLE_CASES)(
    "invalidates the $table keys after the debounce",
    ({ table, expected }) => {
      const fake = createFakeTransport();
      const invalidate = vi
        .spyOn(queryClient, "invalidateQueries")
        .mockResolvedValue();

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
    const invalidate = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue();

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
    const invalidate = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue();

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
    const invalidate = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue();

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
    const invalidate = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue();

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
    const invalidate = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue();

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
    // One topic per attempt, all under this mount's own prefix.
    expect(fake.channelNames().map((name) => name.split("-").at(-1))).toEqual([
      "0",
      "1",
      "2",
    ]);
    expect(
      new Set(fake.channelNames().map((name) => name.slice(0, -1))).size,
    ).toBe(1);
  });

  it("jitters the retry delay by the injected factor", () => {
    const fake = createFakeTransport();
    const { result } = renderHook(
      () =>
        useLeagueBoardRealtime({
          seasonId: 1,
          season: 2026,
          week: 3,
          transport: fake.transport,
          // The bottom of the jitter band: 1_000 ms * 0.8.
          random: () => 0,
        }),
      { wrapper: wrapper(queryClient) },
    );

    act(() => {
      fake.setStatus("SUBSCRIBED");
      fake.setStatus("CHANNEL_ERROR");
      vi.advanceTimersByTime(799);
    });
    expect(fake.channelCount()).toBe(1);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(fake.channelCount()).toBe(2);
    expect(result.current.reconnectAttempts).toBe(1);
  });

  it("gives every mount its own topic, so a StrictMode double mount cannot race", () => {
    const first = createFakeTransport();
    const second = createFakeTransport();
    mount(first);
    mount(second);

    expect(first.channelNames()).toHaveLength(1);
    expect(second.channelNames()).toHaveLength(1);
    expect(first.channelNames()[0]).not.toBe(second.channelNames()[0]);
    // Both are the first channel of their mount, so only the mount id can be telling them apart.
    expect(first.channelNames()[0].endsWith("-0")).toBe(true);
    expect(second.channelNames()[0].endsWith("-0")).toBe(true);
  });

  it("ignores a status callback from a channel it has already torn down", () => {
    const fake = createFakeTransport();
    const invalidate = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue();
    const { result } = mount(fake);

    act(() => {
      fake.setStatus("SUBSCRIBED");
      fake.setStatus("CHANNEL_ERROR");
      vi.advanceTimersByTime(1_000);
    });
    expect(fake.channelCount()).toBe(2);
    invalidate.mockClear();

    // The dead channel's socket can still fire once after removeChannel.
    act(() => {
      fake.setStatusOn(0, "SUBSCRIBED");
    });
    expect(result.current.isConnected).toBe(false);
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("refreshNow reconnects immediately instead of waiting out the backoff", () => {
    const fake = createFakeTransport();
    const { result } = mount(fake);

    act(() => {
      fake.setStatus("SUBSCRIBED");
      fake.setStatus("CHANNEL_ERROR");
      fake.setStatus("CHANNEL_ERROR");
      vi.advanceTimersByTime(1_000);
      fake.setStatus("CHANNEL_ERROR");
    });
    expect(result.current.reconnectAttempts).toBe(1);
    expect(fake.channelCount()).toBe(2);

    act(() => {
      result.current.refreshNow();
    });
    // A new channel on the spot, and the attempt counter back at the bottom of the curve.
    expect(fake.channelCount()).toBe(3);
    expect(result.current.reconnectAttempts).toBe(0);

    // The retry the old channel had armed was cancelled with it, so nothing else rebuilds.
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    expect(fake.channelCount()).toBe(3);

    // And the next failure starts from the one-second rung again.
    act(() => {
      fake.setStatus("CHANNEL_ERROR");
      vi.advanceTimersByTime(1_000);
    });
    expect(fake.channelCount()).toBe(4);
    expect(result.current.reconnectAttempts).toBe(1);
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
          random: NO_JITTER,
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
    const invalidate = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue();
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
    const invalidate = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue();
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
