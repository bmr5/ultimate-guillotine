import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { boardClient } from "@/board/boardClient";

import { mergeTradeSources } from "./derive/merge";
import { resolvePlayerNames } from "./derive/players";
import {
  fetchHistoryMembers,
  fetchHistoryPlayers,
  fetchRegisteredRevisions,
  fetchRegisteredTrades,
  fetchTradeCatalog,
} from "./fetchers";
import { historyKeys } from "./queryKeys";

/** Both tables change by hand a few times a year; five minutes is generous, not stale. */
export const HISTORY_STALE_MS = 5 * 60 * 1000;

export function useTradeCatalog() {
  const catalog = useQuery({
    queryKey: historyKeys.catalog(),
    queryFn: () => fetchTradeCatalog(boardClient),
    staleTime: HISTORY_STALE_MS,
  });
  const registered = useQuery({
    queryKey: historyKeys.registered(),
    queryFn: () => fetchRegisteredTrades(boardClient),
    staleTime: HISTORY_STALE_MS,
  });
  const revisions = useQuery({
    queryKey: historyKeys.revisions(),
    queryFn: () => fetchRegisteredRevisions(boardClient),
    staleTime: HISTORY_STALE_MS,
  });
  const members = useQuery({
    queryKey: historyKeys.members(),
    queryFn: () => fetchHistoryMembers(boardClient),
    staleTime: HISTORY_STALE_MS,
  });
  const players = useQuery({
    queryKey: historyKeys.players(),
    queryFn: () => fetchHistoryPlayers(boardClient),
    staleTime: HISTORY_STALE_MS,
  });

  const merged = useMemo(
    () =>
      mergeTradeSources(
        catalog.data ?? [],
        registered.data ?? [],
        revisions.data ?? [],
        members.data ?? [],
      ),
    [catalog.data, registered.data, revisions.data, members.data],
  );

  /**
   * A registered trade's player assets have no name until the directory names them, so the
   * resolution happens here rather than in a component: the search box and the position filter
   * both read `assets[].name` and `assets[].position`, and a card that resolved its own names
   * would be filtered on the empty ones.
   */
  const trades = useMemo(
    () => resolvePlayerNames(merged.trades, players.data ?? []),
    [merged.trades, players.data],
  );

  const loadedAt = useMemo(() => {
    const stamps = (catalog.data ?? []).map((row) => Date.parse(row.loaded_at));
    return stamps.length === 0 ? null : Math.max(...stamps);
  }, [catalog.data]);

  return {
    trades,
    replacedByBackfill: merged.replacedByBackfill,
    loadedAt,
    members: members.data ?? [],
    // `players` is in the pending set on purpose: without it the first paint would show every
    // registered player asset as "Unlisted player" and then rename it a moment later.
    isPending:
      catalog.isPending ||
      registered.isPending ||
      members.isPending ||
      players.isPending,
    errors: [
      catalog.error,
      registered.error,
      revisions.error,
      members.error,
      players.error,
    ].filter((error): error is Error => error instanceof Error),
  };
}
