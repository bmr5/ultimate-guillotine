import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { supabase } from "@/supabaseClient";

import { boardKeys } from "./queryKeys";
import {
  backoffDelayMs,
  BOARD_REALTIME_TABLES,
  type BoardRealtimeTable,
  keysForTable,
  REALTIME_DEBOUNCE_MS,
  REALTIME_MAX_EVENTS_PER_BURST,
  REALTIME_MAX_WAIT_MS,
} from "./realtime";

/** The slice of a Supabase RealtimeChannel the board uses, so tests can supply a fake. */
export interface FakeableChannel {
  on(
    event: "postgres_changes",
    filter: { event: "*"; schema: "public"; table: string },
    handler: () => void,
  ): FakeableChannel;
  subscribe(handler: (status: string) => void): FakeableChannel;
}

export interface RealtimeTransport {
  channel(name: string): FakeableChannel;
  removeChannel(channel: FakeableChannel): void;
}

export interface UseLeagueBoardRealtimeArgs {
  seasonId: number | null;
  season: number | null;
  week: number | null;
  transport?: RealtimeTransport;
  onConnectionChange?: (isConnected: boolean) => void;
}

export interface LeagueBoardRealtime {
  /** The header turns this into the "reconnecting" label, and the page into its poll interval. */
  isConnected: boolean;
  reconnectAttempts: number;
  refreshNow: () => void;
}

const defaultTransport: RealtimeTransport = {
  channel: (name) => supabase.channel(name) as unknown as FakeableChannel,
  removeChannel: (channel) => {
    void supabase.removeChannel(channel as never);
  },
};

const DISCONNECTED_STATUSES = new Set(["CHANNEL_ERROR", "TIMED_OUT", "CLOSED"]);

export function useLeagueBoardRealtime(
  args: UseLeagueBoardRealtimeArgs,
): LeagueBoardRealtime {
  const { seasonId, season, week, transport, onConnectionChange } = args;
  const queryClient = useQueryClient();

  const [isConnected, setIsConnected] = useState(false);
  const [reconnectAttempts, setReconnectAttempts] = useState(0);
  /**
   * Bumped once per reconnect attempt and used as the effect's only changing dependency. The
   * attempt count itself cannot serve: it resets to zero on a successful subscribe, and that
   * reset would tear down the channel that had just come up.
   */
  const [reconnectNonce, setReconnectNonce] = useState(0);
  const attemptsRef = useRef(0);

  /**
   * The first SUBSCRIBED is the page's own connect, on a board whose queries have just
   * resolved; only a re-subscribe means changes were missed while the socket was down.
   */
  const wasConnectedRef = useRef(false);

  const contextRef = useRef({ seasonId, season, week });
  contextRef.current = { seasonId, season, week };

  const onConnectionChangeRef = useRef(onConnectionChange);
  onConnectionChangeRef.current = onConnectionChange;

  const pendingTablesRef = useRef(new Set<BoardRealtimeTable>());
  const burstEventCountRef = useRef(0);
  const flushTimerRef = useRef<number | null>(null);
  const maxWaitTimerRef = useRef<number | null>(null);

  const clearTimers = useCallback(() => {
    if (flushTimerRef.current !== null) {
      window.clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }
    if (maxWaitTimerRef.current !== null) {
      window.clearTimeout(maxWaitTimerRef.current);
      maxWaitTimerRef.current = null;
    }
  }, []);

  const invalidateAll = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: boardKeys.all });
  }, [queryClient]);

  const refreshNow = useCallback(() => {
    invalidateAll();
  }, [invalidateAll]);

  const flush = useCallback(() => {
    clearTimers();
    const tables = [...pendingTablesRef.current];
    const eventCount = burstEventCountRef.current;
    pendingTablesRef.current = new Set();
    burstEventCountRef.current = 0;

    if (tables.length === 0) {
      return;
    }
    // Past the ceiling, one whole-board refetch is cheaper than a key-by-key storm.
    if (eventCount > REALTIME_MAX_EVENTS_PER_BURST) {
      invalidateAll();
      return;
    }

    const seen = new Set<string>();
    for (const table of tables) {
      for (const queryKey of keysForTable(table, contextRef.current)) {
        const fingerprint = JSON.stringify(queryKey);
        if (seen.has(fingerprint)) {
          continue;
        }
        seen.add(fingerprint);
        void queryClient.invalidateQueries({ queryKey });
      }
    }
  }, [clearTimers, invalidateAll, queryClient]);

  const enqueue = useCallback(
    (table: BoardRealtimeTable) => {
      pendingTablesRef.current.add(table);
      burstEventCountRef.current += 1;
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current);
      }
      flushTimerRef.current = window.setTimeout(flush, REALTIME_DEBOUNCE_MS);
      // A steady write just under the debounce would otherwise reset the trailing timer
      // forever; this ceiling on the wait is what guarantees the board still refetches.
      if (maxWaitTimerRef.current === null) {
        maxWaitTimerRef.current = window.setTimeout(flush, REALTIME_MAX_WAIT_MS);
      }
    },
    [flush],
  );

  useEffect(() => {
    const active = transport ?? defaultTransport;
    let retryTimer: number | null = null;
    let cancelled = false;

    const channel = active.channel(`league-board-${reconnectNonce}`);
    for (const table of BOARD_REALTIME_TABLES) {
      channel.on("postgres_changes", { event: "*", schema: "public", table }, () => {
        enqueue(table);
      });
    }

    channel.subscribe((status) => {
      if (cancelled) {
        return;
      }
      if (status === "SUBSCRIBED") {
        setIsConnected(true);
        attemptsRef.current = 0;
        setReconnectAttempts(0);
        onConnectionChangeRef.current?.(true);
        if (wasConnectedRef.current) {
          // Anything that changed while the channel was down was missed.
          invalidateAll();
        }
        wasConnectedRef.current = true;
        return;
      }
      if (DISCONNECTED_STATUSES.has(status)) {
        setIsConnected(false);
        onConnectionChangeRef.current?.(false);
        if (retryTimer === null) {
          retryTimer = window.setTimeout(() => {
            retryTimer = null;
            attemptsRef.current += 1;
            setReconnectAttempts(attemptsRef.current);
            setReconnectNonce((nonce) => nonce + 1);
          }, backoffDelayMs(attemptsRef.current));
        }
      }
    });

    return () => {
      cancelled = true;
      if (retryTimer !== null) {
        window.clearTimeout(retryTimer);
      }
      // A rebuilt channel re-subscribes and refetches the whole board, so a queue held over
      // from the dead one would only duplicate that work.
      clearTimers();
      pendingTablesRef.current = new Set();
      burstEventCountRef.current = 0;
      active.removeChannel(channel);
    };
  }, [clearTimers, enqueue, invalidateAll, reconnectNonce, transport]);

  return { isConnected, reconnectAttempts, refreshNow };
}
