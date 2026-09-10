import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { boardClient } from "@/board/boardClient";

import { mergeTradeSources } from "./derive/merge";
import { playerIdsToResolve, resolvePlayerNames } from "./derive/players";
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

/** A failed query, named by the part of the page it was loading. */
export interface TradeCatalogError {
  source: string;
  error: Error;
}

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

  // The directory is asked for the players these trades reference and no others, so the query
  // cannot be composed until the merge has run.
  const playerIds = useMemo(
    () => playerIdsToResolve(merged.trades),
    [merged.trades],
  );

  const players = useQuery({
    queryKey: historyKeys.players(playerIds),
    queryFn: () => fetchHistoryPlayers(boardClient, playerIds),
    staleTime: HISTORY_STALE_MS,
    enabled: playerIds.length > 0,
  });

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

  const errors = useMemo(
    () =>
      (
        [
          { source: "Trade catalog", error: catalog.error },
          { source: "Registered trades", error: registered.error },
          { source: "Trade revisions", error: revisions.error },
          { source: "Members", error: members.error },
          { source: "Players", error: players.error },
        ] satisfies { source: string; error: Error | null }[]
      ).filter(
        (entry): entry is TradeCatalogError => entry.error instanceof Error,
      ),
    [
      catalog.error,
      registered.error,
      revisions.error,
      members.error,
      players.error,
    ],
  );

  return {
    trades,
    replacedByBackfill: merged.replacedByBackfill,
    loadedAt,
    members: members.data ?? [],
    // `revisions` is in the pending set even though its rows only decorate a registered trade:
    // without it the first paint shows every registered trade with no assets and no week, then
    // fills them in. `players` is in it for the same reason — otherwise every registered player
    // asset paints as "Unlisted player" and is renamed a moment later.
    //
    // `players.isLoading`, not `isPending`: the directory query is disabled while there is
    // nothing to look up, and a disabled query stays `pending` forever, so `isPending` would
    // leave a catalog-only league on the skeleton for good.
    isPending:
      catalog.isPending ||
      registered.isPending ||
      revisions.isPending ||
      members.isPending ||
      players.isLoading,
    errors,
  };
}
