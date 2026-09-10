import { useQuery } from "@tanstack/react-query";

import { boardClient } from "@/board/boardClient";
import { fetchNflState } from "@/board/fetchers";
import { boardKeys } from "@/board/queryKeys";

export interface CurrentSeason {
  /** The NFL season `nfl_state` says it is, or `null` while unknown or when the fetch failed. */
  season: number | null;
  /** True until the first fetch has either resolved or failed. */
  isPending: boolean;
}

/**
 * The season `/trades` opens on.
 *
 * Read from `nfl_state` — the same row the board scopes itself to, on the same query key, so a
 * visitor coming from the board pays no second request — rather than from the newest season in
 * the catalog. The two differ exactly when it matters: in the weeks before a season's first
 * trade the catalog's newest season is last year's, and opening on it would present a finished
 * season as the current one.
 *
 * The board refetches this key every fifteen seconds while it is mounted; here it is only ever
 * read for the year, which changes once a season, so the observer asks for nothing more.
 */
export function useCurrentSeason(): CurrentSeason {
  const nflState = useQuery({
    queryKey: boardKeys.nflState(),
    queryFn: () => fetchNflState(boardClient),
    staleTime: Infinity,
  });
  return {
    season: nflState.data?.season ?? null,
    isPending: nflState.isPending,
  };
}
