import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { boardClient } from "@/board/boardClient";
import { fetchPlayers, type PlayerRow } from "@/board/fetchers";
import type { BoardQueryError } from "@/board/useBoardData";
import { historyKeys } from "@/history/queryKeys";
import type { CatalogTrade } from "@/history/types";
import { useTradeCatalog } from "@/history/useTradeCatalog";

import {
  fetchPlayerTransactions,
  fetchSeasonScores,
  type SeasonScoreRow,
  type TransactionMoveRow,
  type TransactionRow,
} from "./fetchers";
import { playerKeys } from "./queryKeys";

export interface PlayerCardData {
  transactions: TransactionRow[];
  moves: TransactionMoveRow[];
  seasonScores: SeasonScoreRow[];
  directory: PlayerRow | null;
  otherPlayers: PlayerRow[];
  registered: CatalogTrade[];
  isPending: boolean;
  errors: BoardQueryError[];
  refetch: () => void;
}

/** Ten seconds: a card is open for a moment, and a second open inside it should not refetch. */
const CARD_STALE_MS = 10_000;

/**
 * The card's reads: the player's transactions (then the other players they name), the season's
 * weekly scores, the directory row for a player the board does not hold, and the trades page's
 * registered trades. Mounted only while a card is open, so the trades hook runs only then.
 */
export function usePlayerCard(input: {
  seasonId: number | null;
  sleeperPlayerId: string;
}): PlayerCardData {
  const queryClient = useQueryClient();
  const enabled = input.seasonId !== null;
  const seasonId = input.seasonId ?? 0;

  const transactions = useQuery({
    queryKey: playerKeys.transactions(seasonId, input.sleeperPlayerId),
    queryFn: () =>
      fetchPlayerTransactions(boardClient, seasonId, input.sleeperPlayerId),
    enabled,
    staleTime: CARD_STALE_MS,
  });
  const scores = useQuery({
    queryKey: playerKeys.seasonScores(seasonId),
    queryFn: () => fetchSeasonScores(boardClient, seasonId),
    enabled,
    staleTime: CARD_STALE_MS,
  });
  const directory = useQuery({
    queryKey: playerKeys.directory([input.sleeperPlayerId]),
    queryFn: () => fetchPlayers(boardClient, [input.sleeperPlayerId]),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const otherIds = useMemo(() => {
    const ids = new Set<string>();
    for (const move of transactions.data?.moves ?? []) {
      if (move.sleeper_player_id !== input.sleeperPlayerId) {
        ids.add(move.sleeper_player_id);
      }
    }
    return [...ids].sort();
  }, [transactions.data, input.sleeperPlayerId]);
  const others = useQuery({
    queryKey: playerKeys.directory(otherIds),
    queryFn: () => fetchPlayers(boardClient, otherIds),
    enabled: otherIds.length > 0,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const catalog = useTradeCatalog();

  const sections: [string, { error: Error | null }][] = [
    ["Transactions", transactions],
    ["Season scores", scores],
    ["Player", directory],
    ["Other players", others],
  ];
  const errors: BoardQueryError[] = [
    ...sections
      .filter(([, query]) => query.error !== null)
      .map(([section, query]) => ({
        section,
        message: query.error?.message ?? "Unknown error",
      })),
    ...catalog.errors.map((entry) => ({
      section: entry.source,
      message: entry.error.message,
    })),
  ];

  return {
    transactions: transactions.data?.transactions ?? [],
    moves: transactions.data?.moves ?? [],
    seasonScores: scores.data ?? [],
    directory: directory.data?.[0] ?? null,
    otherPlayers: others.data ?? [],
    registered: catalog.trades,
    // isLoading, not isPending: a disabled query stays pending forever (see useBoardData).
    isPending:
      transactions.isLoading ||
      scores.isLoading ||
      directory.isLoading ||
      others.isLoading ||
      catalog.isPending,
    errors,
    refetch: () => {
      void queryClient.invalidateQueries({ queryKey: playerKeys.all });
      void queryClient.invalidateQueries({ queryKey: historyKeys.catalog() });
      void queryClient.invalidateQueries({ queryKey: historyKeys.registered() });
      void queryClient.invalidateQueries({ queryKey: historyKeys.revisions() });
    },
  };
}
