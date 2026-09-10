import { useMemo } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";

import { boardClient } from "@/board/boardClient";
import {
  fetchDraftPicks,
  fetchLatestSeason,
  fetchMembers,
  fetchPlayers,
  fetchSeasonByYear,
  fetchTeams,
  type DraftPickRow,
  type MemberRow,
  type PlayerRow,
  type TeamRow,
} from "@/board/fetchers";
import { boardKeys, fingerprintIds } from "@/board/queryKeys";
import type { BoardQueryError } from "@/board/useBoardData";
import { useCurrentSeason } from "@/history/useCurrentSeason";

export interface DraftPageData {
  season: number | null;
  /** `seasons.waiver_budget`, for the auction budget the unspent figures derive from. */
  waiverBudget: number | null;
  picks: DraftPickRow[];
  teams: TeamRow[];
  members: MemberRow[];
  players: PlayerRow[];
  isPending: boolean;
  errors: BoardQueryError[];
  refetchAll: () => void;
}

/** The auction is a fact; the directory is a lookup. Neither goes stale on a timer. */
const STATIC = {
  staleTime: Number.POSITIVE_INFINITY,
  refetchInterval: false as const,
};

/**
 * The season the same way the board resolves it — `nfl_state`'s year, or the newest row in the
 * offseason — then the picks, the teams and members behind the owner labels, and the names.
 * Every key is the board's, so a visitor coming from the board pays for nothing twice.
 */
export function useDraftPage(): DraftPageData {
  const queryClient = useQueryClient();
  const current = useCurrentSeason();
  const seasonRow = useQuery({
    queryKey: boardKeys.season(current.season ?? 0),
    queryFn: () => fetchSeasonByYear(boardClient, current.season as number),
    enabled: current.season !== null,
    ...STATIC,
  });
  const latestSeason = useQuery({
    queryKey: boardKeys.latestSeason(),
    queryFn: () => fetchLatestSeason(boardClient),
    enabled: seasonRow.isSuccess && seasonRow.data === null,
    ...STATIC,
  });
  const resolved = seasonRow.data ?? latestSeason.data ?? null;
  const seasonId = resolved?.id ?? null;
  const hasSeason = seasonId !== null;

  const picks = useQuery({
    queryKey: boardKeys.draftPicks(seasonId ?? 0),
    queryFn: () => fetchDraftPicks(boardClient, seasonId as number),
    enabled: hasSeason,
    ...STATIC,
  });
  const teams = useQuery({
    queryKey: boardKeys.teams(seasonId ?? 0),
    queryFn: () => fetchTeams(boardClient, seasonId as number),
    enabled: hasSeason,
    ...STATIC,
  });
  const members = useQuery({
    queryKey: boardKeys.members(),
    queryFn: () => fetchMembers(boardClient),
    ...STATIC,
  });
  const ids = useMemo(
    () =>
      [...new Set((picks.data ?? []).map((pick) => pick.sleeper_player_id))].sort(),
    [picks.data],
  );
  const fingerprint = useMemo(() => fingerprintIds(ids), [ids]);
  const players = useQuery({
    queryKey: boardKeys.players(seasonId ?? 0, fingerprint),
    queryFn: () => fetchPlayers(boardClient, ids),
    enabled: hasSeason && ids.length > 0,
    placeholderData: keepPreviousData,
    ...STATIC,
  });

  const sections: [string, { error: Error | null }][] = [
    ["Season", seasonRow],
    ["Season", latestSeason],
    ["Draft", picks],
    ["Teams", teams],
    ["Owners", members],
    ["Players", players],
  ];
  const errors: BoardQueryError[] = sections
    .filter(([, query]) => query.error !== null)
    .map(([section, query]) => ({
      section,
      message: query.error?.message ?? "Unknown error",
    }));

  return {
    season: resolved?.year ?? null,
    waiverBudget: resolved?.waiver_budget ?? null,
    picks: picks.data ?? [],
    teams: teams.data ?? [],
    members: members.data ?? [],
    players: players.data ?? [],
    // isLoading, not isPending: a disabled query stays pending forever (see useBoardData).
    isPending:
      current.isPending ||
      seasonRow.isLoading ||
      latestSeason.isLoading ||
      picks.isLoading ||
      teams.isLoading ||
      members.isLoading ||
      players.isLoading,
    errors,
    refetchAll: () => {
      void queryClient.invalidateQueries({ queryKey: boardKeys.all });
    },
  };
}
