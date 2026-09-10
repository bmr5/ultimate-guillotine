import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { supabase } from "@/supabaseClient";

import { boardKeys } from "./queryKeys";
import {
  backoffDelayMs,
  BOARD_REALTIME_TABLES,
  keysForTable,
  REALTIME_DEBOUNCE_MS,
  REALTIME_MAX_EVENTS_PER_TABLE,
  REALTIME_MAX_WAIT_MS,
  type BoardRealtimeTable,
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
  /** Injectable source for the backoff jitter, so tests get a fixed delay. */
  random?: () => number;
}

export interface LeagueBoardRealtime {
  /** The page turns this into its poll interval. */
  isConnected: boolean;
  /**
   * True from the first successful subscribe onwards, and never false again.
   *
   * `isConnected` is false for the whole of a cold load — the socket cannot have come up before
   * the page mounted — so a paused banner and a "reconnecting" label gated on `!isConnected`
   * alone flash on every single visit and say something untrue while they do. Both are gated on
   * `hasConnectedOnce && !isConnected` instead, which is the only state that means *dropped*.
   */
  hasConnectedOnce: boolean;
  reconnectAttempts: number;
  /**
   * Refetches the whole board and rebuilds the channel immediately. The disconnected banner's
   * refresh button is the one place a person overrides the backoff, so it must not have to wait
   * out a pending retry timer that may be most of half a minute away.
   */
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
  const { seasonId, season, week, transport, onConnectionChange, random } =
    args;
  const queryClient = useQueryClient();

  const [isConnected, setIsConnected] = useState(false);
  const [hasConnectedOnce, setHasConnectedOnce] = useState(false);
  const [reconnectAttempts, setReconnectAttempts] = useState(0);
  /**
   * Bumped once per reconnect attempt and used as the effect's only changing dependency. The
   * attempt count itself cannot serve: it resets to zero on a successful subscribe, and that
   * reset would tear down the channel that had just come up.
   */
  const [reconnectNonce, setReconnectNonce] = useState(0);
  const attemptsRef = useRef(0);
  /**
   * A Realtime topic is a server-side identity: two channels on one topic are the same
   * subscription, and React StrictMode mounts every hook twice, so a topic built from the
   * reconnect nonce alone would have the discarded first mount and the surviving second one
   * racing for it — the teardown of the first can drop the second. `useId` gives every mount
   * its own id.
   */
  const mountId = useId();

  /**
   * The three "latest" refs below are written from an effect rather than during render, which
   * is the one place React allows a ref to be assigned. Every reader is an effect, a channel
   * callback or a timer — all of them run after the sync effect has committed the new value.
   */
  const randomRef = useRef(random);
  useEffect(() => {
    randomRef.current = random;
  }, [random]);

  /**
   * The first SUBSCRIBED is the page's own connect, on a board whose queries have just
   * resolved; only a re-subscribe means changes were missed while the socket was down.
   */
  const wasConnectedRef = useRef(false);

  const contextRef = useRef({ seasonId, season, week });
  useEffect(() => {
    contextRef.current = { seasonId, season, week };
  }, [seasonId, season, week]);

  const onConnectionChangeRef = useRef(onConnectionChange);
  useEffect(() => {
    onConnectionChangeRef.current = onConnectionChange;
  }, [onConnectionChange]);

  /**
   * The tables a burst has touched, each with how many events landed on it. Keyed per table
   * because the burst ceiling is per table: the scores job and the projections job share a
   * minute boundary through a game window, and a count pooled across both would call an
   * ordinary Sunday a storm and refetch the whole board every five minutes.
   */
  const pendingTablesRef = useRef(new Map<BoardRealtimeTable, number>());
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
    // Bumping the nonce tears the current channel down and builds a new one on the spot, which
    // cancels any pending retry timer; zeroing the attempts puts the next failure back at the
    // bottom of the backoff curve, where a person who just asked for a retry expects it.
    attemptsRef.current = 0;
    setReconnectAttempts(0);
    setReconnectNonce((nonce) => nonce + 1);
  }, [invalidateAll]);

  const flush = useCallback(() => {
    clearTimers();
    const counts = pendingTablesRef.current;
    pendingTablesRef.current = new Map();

    if (counts.size === 0) {
      return;
    }
    // Past the ceiling, one whole-board refetch is cheaper than a key-by-key storm — but only
    // when a single table is the one flooding. Several tables each writing a normal run's worth
    // of rows on the same boundary is the every-five-minutes case, not a storm.
    const flooded = [...counts.values()].some(
      (count) => count > REALTIME_MAX_EVENTS_PER_TABLE,
    );
    if (flooded) {
      invalidateAll();
      return;
    }

    const seen = new Set<string>();
    for (const table of counts.keys()) {
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
      const counts = pendingTablesRef.current;
      counts.set(table, (counts.get(table) ?? 0) + 1);
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current);
      }
      flushTimerRef.current = window.setTimeout(flush, REALTIME_DEBOUNCE_MS);
      // A steady write just under the debounce would otherwise reset the trailing timer
      // forever; this ceiling on the wait is what guarantees the board still refetches.
      if (maxWaitTimerRef.current === null) {
        maxWaitTimerRef.current = window.setTimeout(
          flush,
          REALTIME_MAX_WAIT_MS,
        );
      }
    },
    [flush],
  );

  useEffect(() => {
    const active = transport ?? defaultTransport;
    let retryTimer: number | null = null;
    let cancelled = false;

    const channel = active.channel(
      `league-board-${mountId}-${reconnectNonce}`,
    );
    // Unfiltered on purpose: `roster_holdings`, `team_season_state` and `team_week_projections`
    // all carry a `season_id`, but the league runs exactly one live season at a time, so every
    // event on them belongs to the season the board is showing. `keysForTable` scopes the
    // invalidation to the board's own season anyway, so a stray row from an archived season
    // would cost a redundant refetch and nothing else. If a second live season ever exists, add
    // `filter: \`season_id=eq.${seasonId}\`` here (and gate the subscribe on a resolved id).
    for (const table of BOARD_REALTIME_TABLES) {
      channel.on(
        "postgres_changes",
        { event: "*", schema: "public", table },
        () => {
          enqueue(table);
        },
      );
    }

    channel.subscribe((status) => {
      if (cancelled) {
        return;
      }
      if (status === "SUBSCRIBED") {
        setIsConnected(true);
        // Latches on the first subscribe and stays latched: past this point a `false`
        // `isConnected` is a drop, which is the only thing the board's paused chrome may say.
        setHasConnectedOnce(true);
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
          retryTimer = window.setTimeout(
            () => {
              retryTimer = null;
              attemptsRef.current += 1;
              setReconnectAttempts(attemptsRef.current);
              setReconnectNonce((nonce) => nonce + 1);
            },
            backoffDelayMs(attemptsRef.current, randomRef.current),
          );
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
      pendingTablesRef.current = new Map();
      active.removeChannel(channel);
    };
  }, [clearTimers, enqueue, invalidateAll, mountId, reconnectNonce, transport]);

  return { isConnected, hasConnectedOnce, reconnectAttempts, refreshNow };
}
