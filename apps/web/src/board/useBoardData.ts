import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";

import { boardClient } from "./boardClient";
import { joinBoardTeams } from "./derive/join";
import {
  fetchFinalRosters,
  fetchMembers,
  fetchNflState,
  fetchPlayerProjections,
  fetchPlayers,
  fetchRosterHoldings,
  fetchSeasonByYear,
  fetchTeamSeasonState,
  fetchTeamWeekProjections,
  fetchTeams,
  fetchWeeklyResults,
} from "./fetchers";
import { boardKeys, fingerprintIds } from "./queryKeys";
import type { BoardTeam } from "./types";

export interface BoardDataOptions {
  /** false while Realtime is healthy; 60_000 while it is not. */
  pollingMs: number | false;
}

export interface BoardQueryError {
  section: string;
  message: string;
}

export interface BoardDataResult {
  season: number | null;
  week: number | null;
  seasonId: number | null;
  teams: BoardTeam[];
  isPending: boolean;
  isEmpty: boolean;
  errors: BoardQueryError[];
  /**
   * When the projections were last pulled: the newest `team_week_projections.computed_at`
   * for the week. This is what the header shows — not when the browser last refetched.
   */
  projectionsUpdatedAt: number | null;
  refetchAll: () => void;
}

export function useBoardData(options: BoardDataOptions): BoardDataResult {
  const queryClient = useQueryClient();
  const shared = {
    refetchOnWindowFocus: true as const,
    refetchInterval: options.pollingMs,
    staleTime: 15_000,
  };

  const nflState = useQuery({
    queryKey: boardKeys.nflState(),
    queryFn: () => fetchNflState(boardClient),
    ...shared,
  });

  // Spec issue 7: the season and week the whole board is scoped to come from nfl_state, never
  // from a hardcoded year. Every select below is filtered by one or both.
  const season = nflState.data?.season ?? null;
  const week = nflState.data?.week ?? null;

  const seasonRow = useQuery({
    queryKey: boardKeys.season(season ?? 0),
    queryFn: () => fetchSeasonByYear(boardClient, season as number),
    enabled: season !== null,
    ...shared,
  });

  const seasonId = seasonRow.data?.id ?? null;
  const hasSeason = seasonId !== null;

  const teams = useQuery({
    queryKey: boardKeys.teams(seasonId ?? 0),
    queryFn: () => fetchTeams(boardClient, seasonId as number),
    enabled: hasSeason,
    ...shared,
  });

  const members = useQuery({
    queryKey: boardKeys.members(),
    queryFn: () => fetchMembers(boardClient),
    ...shared,
  });

  const state = useQuery({
    queryKey: boardKeys.teamSeasonState(seasonId ?? 0),
    queryFn: () => fetchTeamSeasonState(boardClient, seasonId as number),
    enabled: hasSeason,
    ...shared,
  });

  const teamProjections = useQuery({
    queryKey: boardKeys.teamWeekProjections(seasonId ?? 0, week ?? 0),
    queryFn: () =>
      fetchTeamWeekProjections(boardClient, seasonId as number, week as number),
    enabled: hasSeason && week !== null,
    ...shared,
  });

  const holdings = useQuery({
    queryKey: boardKeys.rosterHoldings(seasonId ?? 0),
    queryFn: () => fetchRosterHoldings(boardClient, seasonId as number),
    enabled: hasSeason,
    ...shared,
  });

  const weeklyResults = useQuery({
    queryKey: boardKeys.weeklyResults(seasonId ?? 0),
    queryFn: () => fetchWeeklyResults(boardClient, seasonId as number),
    enabled: hasSeason,
    ...shared,
  });

  const finalRosters = useQuery({
    queryKey: boardKeys.finalRosters(seasonId ?? 0),
    queryFn: () => fetchFinalRosters(boardClient, seasonId as number),
    enabled: hasSeason,
    ...shared,
  });

  // A player frozen onto an eliminated team's snapshot has usually been dropped, so he is no
  // longer in roster_holdings. Both id sets are needed or those rows render as "Unknown player".
  const heldPlayerIds = useMemo(() => {
    const ids = new Set<string>();
    for (const holding of holdings.data ?? []) {
      ids.add(holding.sleeper_player_id);
    }
    for (const snapshot of finalRosters.data ?? []) {
      for (const holding of snapshot.holdings) {
        ids.add(holding.sleeper_player_id);
      }
    }
    return [...ids].sort();
  }, [holdings.data, finalRosters.data]);

  // The `.in()` list is part of the request, so the id set is part of the key. Keyed on the
  // season alone, a waiver claim or a fresh snapshot would keep hitting the directory fetched
  // for the older, smaller set and the new names would read as "Unknown player".
  const heldIdsFingerprint = useMemo(
    () => fingerprintIds(heldPlayerIds),
    [heldPlayerIds],
  );

  const players = useQuery({
    queryKey: boardKeys.players(seasonId ?? 0, heldIdsFingerprint),
    queryFn: () => fetchPlayers(boardClient, heldPlayerIds),
    enabled: hasSeason && heldPlayerIds.length > 0,
    ...shared,
  });

  const playerProjections = useQuery({
    queryKey: boardKeys.playerProjections(season ?? 0, week ?? 0, heldIdsFingerprint),
    queryFn: () =>
      fetchPlayerProjections(
        boardClient,
        season as number,
        week as number,
        heldPlayerIds,
      ),
    enabled: season !== null && week !== null && heldPlayerIds.length > 0,
    ...shared,
  });

  const boardTeams = useMemo(
    () =>
      joinBoardTeams({
        teams: teams.data ?? [],
        members: members.data ?? [],
        teamSeasonState: state.data ?? [],
        teamWeekProjections: teamProjections.data ?? [],
        rosterHoldings: holdings.data ?? [],
        players: players.data ?? [],
        playerProjections: playerProjections.data ?? [],
        weeklyResults: weeklyResults.data ?? [],
        finalRosters: finalRosters.data ?? [],
      }),
    [
      teams.data,
      members.data,
      state.data,
      teamProjections.data,
      holdings.data,
      players.data,
      playerProjections.data,
      weeklyResults.data,
      finalRosters.data,
    ],
  );

  // The last-pull time the header shows: when the projections were computed, not when the
  // browser last refetched them. A refetch that returns identical rows must not look fresher.
  const projectionsUpdatedAt = useMemo(() => {
    let newest: number | null = null;
    for (const row of teamProjections.data ?? []) {
      const computedAt = Date.parse(row.computed_at);
      if (Number.isNaN(computedAt)) {
        continue;
      }
      newest = newest === null ? computedAt : Math.max(newest, computedAt);
    }
    return newest;
  }, [teamProjections.data]);

  const sections: [string, { error: Error | null }][] = [
    ["NFL week", nflState],
    ["Season", seasonRow],
    ["Teams", teams],
    ["Owners", members],
    ["Team state", state],
    ["Projections", teamProjections],
    ["Rosters", holdings],
    ["Players", players],
    ["Player projections", playerProjections],
    ["Weekly results", weeklyResults],
    ["Final rosters", finalRosters],
  ];

  const errors: BoardQueryError[] = sections
    .filter(([, query]) => query.error !== null)
    .map(([section, query]) => ({
      section,
      message: query.error?.message ?? "Unknown error",
    }));

  // isLoading, not isPending. A disabled query — teams before the season resolves, and every
  // query below it — sits at status "pending" forever, so isPending would leave the board
  // spinning on an empty database instead of reaching the empty state. isLoading is
  // `isPending && isFetching`, which a disabled query never is.
  const isPending = nflState.isLoading || seasonRow.isLoading || teams.isLoading;

  return {
    season,
    week,
    seasonId,
    teams: boardTeams,
    isPending,
    // A failed teams query is not an empty league: the empty state claims there is nothing to
    // show, which is a different statement from "this request did not come back".
    isEmpty: !isPending && teams.error === null && boardTeams.length === 0,
    errors,
    projectionsUpdatedAt,
    refetchAll: () => {
      void queryClient.invalidateQueries({ queryKey: boardKeys.all });
    },
  };
}
