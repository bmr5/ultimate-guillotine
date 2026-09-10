import { useMemo } from "react";
import {
  keepPreviousData,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { boardClient } from "./boardClient";
import { joinBoardTeams } from "./derive/join";
import { latestFinalWeek } from "./derive/records";
import { parseRosterPositions } from "./derive/roster";
import { newestScoreSyncedAt } from "./derive/score";
import {
  fetchDraftPicks,
  fetchFinalRosters,
  fetchLatestSeason,
  fetchMembers,
  fetchNflState,
  fetchPlayerProjections,
  fetchPlayers,
  fetchRosterHoldings,
  fetchSeasonByYear,
  fetchTeams,
  fetchTeamSeasonState,
  fetchTeamWeekProjections,
  fetchTeamWeekScores,
  fetchWeeklyResults,
  type DraftPickRow,
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
  /**
   * The year of the `seasons` row the board is actually showing — which is `nfl_state.season`
   * during a season the league has a row for, and the newest row's year otherwise.
   */
  season: number | null;
  /**
   * The week every week-scoped query is filtered by. Outside the regular season this is the
   * last week with final results, not `nfl_state.week`: that number names a week this league
   * never played, so filtering to it returns nothing and blanks the board.
   */
  week: number | null;
  /** The week the header names: `display_week` once the regular season is over. */
  displayWeek: number | null;
  /** True when `nfl_state.season` has no `seasons` row and the newest one is standing in. */
  isSeasonFallback: boolean;
  /** True when `nfl_state.season_type` is anything but `regular`. */
  isOffRegularSeason: boolean;
  seasonId: number | null;
  /**
   * The league's lineup, from `seasons.roster_positions` — `["QB","RB","RB",...]`. Empty until
   * the season row lands, which reads as "no lineup known": every starter still renders and no
   * slot is called empty, rather than the board inventing holes it cannot see.
   */
  rosterPositions: string[];
  /** The season's auction, whole; the card's context line is computed from it. */
  draftPicks: DraftPickRow[];
  /** `teams.id` -> `members.id`, for matching a Sleeper trade to a registered one. */
  memberIdByTeamId: ReadonlyMap<number, number>;
  teams: BoardTeam[];
  isPending: boolean;
  isEmpty: boolean;
  errors: BoardQueryError[];
  /**
   * When the projections were last computed: the newest `team_week_projections.computed_at`
   * for the week. Not when the browser last refetched — a refetch that returns identical rows
   * must not look fresher.
   *
   * This used to be the header's only stamp, and it is the "why does it show that it updated
   * at 9:30PM" half of Ben's complaint: `computed_at` only moves when a projection is actually
   * recomputed. It is still shown, as the smaller second line, because it is the honest answer
   * for the projection figure beside the score.
   */
  projectionsUpdatedAt: number | null;
  /**
   * When the scores were last pulled: the newest `team_week_scores.synced_at` for the week,
   * or null when no team has a score row. The sync moves this on every run, score or no score,
   * so this is the stamp the header leads with whenever it exists.
   */
  scoresUpdatedAt: number | null;
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
  const nflSeason = nflState.data?.season ?? null;
  const nflWeek = nflState.data?.week ?? null;
  /**
   * `pre`, `post` and `off` all mean the same thing to this board: `nfl_state.week` is no
   * longer a week the league played. A null season_type (nfl_state has not resolved) is treated
   * as regular, since nothing is scoped yet anyway.
   */
  const isOffRegularSeason =
    nflState.data != null && nflState.data.season_type !== "regular";

  const seasonRow = useQuery({
    queryKey: boardKeys.season(nflSeason ?? 0),
    queryFn: () => fetchSeasonByYear(boardClient, nflSeason as number),
    enabled: nflSeason !== null,
    ...shared,
  });

  /**
   * `nfl_state.season` rolls to the next year the moment the NFL does — months before this
   * league has a `seasons` row for it. Without this hop the season lookup resolves to `null`,
   * every query below it stays disabled, and the board reads as empty all offseason. Asked for
   * only once the year-scoped lookup has come back empty, so an in-season board never runs it.
   */
  const latestSeason = useQuery({
    queryKey: boardKeys.latestSeason(),
    queryFn: () => fetchLatestSeason(boardClient),
    enabled: seasonRow.isSuccess && seasonRow.data === null,
    ...shared,
  });

  const isSeasonFallback =
    seasonRow.isSuccess &&
    seasonRow.data === null &&
    (latestSeason.data ?? null) !== null;
  const resolvedSeason = seasonRow.data ?? latestSeason.data ?? null;

  const seasonId = resolvedSeason?.id ?? null;
  const hasSeason = seasonId !== null;
  /**
   * The year of the row actually on screen, not `nfl_state.season`. `player_projections` is
   * keyed on the plain year rather than the season id, so asking for 2027's projections while
   * showing 2026's rosters would return nothing at all.
   */
  const season = resolvedSeason?.year ?? null;
  /**
   * jsonb, so it is `string[]` by declaration only; `parseRosterPositions` is what makes it one.
   * Memoized on the season row because it is a prop on every memoized card below: a fresh array
   * identity each render would re-render the whole board on every tick.
   */
  const rosterPositions = useMemo(
    () => parseRosterPositions(resolvedSeason?.roster_positions),
    [resolvedSeason],
  );

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

  /**
   * The week the numbers come from.
   *
   * In the regular season that is `nfl_state.week`. Once `season_type` leaves `regular` the
   * board falls back to the last week with final results — `nfl_state.week` then names a
   * post-season week this league never played, and every week-scoped filter would match no
   * rows and blank the board. With no final week at all there is nothing better than the raw
   * week, which degrades to an empty week rather than a wrong one; the header carries the
   * caveat either way.
   */
  const lastScoredWeek = useMemo(
    () => latestFinalWeek(weeklyResults.data ?? []),
    [weeklyResults.data],
  );
  const week = isOffRegularSeason ? lastScoredWeek ?? nflWeek : nflWeek;
  /** What the header names. Sleeper's own post-season week number, not the scoped week. */
  const displayWeek = isOffRegularSeason
    ? nflState.data?.display_week ?? nflWeek
    : nflWeek;
  /**
   * Outside the regular season the scoped week is not known until `weekly_results` lands, so
   * the week-scoped queries wait for it rather than firing once for `nfl_state.week` and again
   * for the real one.
   */
  const hasWeekScope =
    !isOffRegularSeason || weeklyResults.isSuccess || weeklyResults.isError;

  const teamProjections = useQuery({
    queryKey: boardKeys.teamWeekProjections(seasonId ?? 0, week ?? 0),
    queryFn: () =>
      fetchTeamWeekProjections(boardClient, seasonId as number, week as number),
    enabled: hasSeason && week !== null && hasWeekScope,
    ...shared,
  });

  const teamScores = useQuery({
    queryKey: boardKeys.teamWeekScores(seasonId ?? 0, week ?? 0),
    queryFn: () =>
      fetchTeamWeekScores(boardClient, seasonId as number, week as number),
    enabled: hasSeason && week !== null && hasWeekScope,
    ...shared,
  });

  const finalRosters = useQuery({
    queryKey: boardKeys.finalRosters(seasonId ?? 0),
    queryFn: () => fetchFinalRosters(boardClient, seasonId as number),
    enabled: hasSeason,
    ...shared,
  });

  const draftPicks = useQuery({
    queryKey: boardKeys.draftPicks(seasonId ?? 0),
    queryFn: () => fetchDraftPicks(boardClient, seasonId as number),
    enabled: hasSeason,
    ...shared,
    // The auction is a fact that changes once a year. Window focus still refetches it.
    staleTime: Number.POSITIVE_INFINITY,
    refetchInterval: false as const,
  });

  const memberIdByTeamId = useMemo(
    () => new Map((teams.data ?? []).map((team) => [team.id, team.member_id])),
    [teams.data],
  );

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
    // A fingerprint change is a brand-new cache entry with no data, so without this every
    // already-known name blinks to "Unknown player …" for a paint while the new key loads.
    placeholderData: keepPreviousData,
    // The player directory is a static lookup — a name, a position, an NFL team. Nothing about
    // it goes stale on a timer, and the only thing that should refetch it is a new id set,
    // which is already a new key. So no poll, and no staleness clock.
    staleTime: Number.POSITIVE_INFINITY,
    refetchInterval: false as const,
  });

  const playerProjections = useQuery({
    queryKey: boardKeys.playerProjections(
      season ?? 0,
      week ?? 0,
      heldIdsFingerprint,
    ),
    queryFn: () =>
      fetchPlayerProjections(
        boardClient,
        season as number,
        week as number,
        heldPlayerIds,
      ),
    enabled:
      season !== null &&
      week !== null &&
      hasWeekScope &&
      heldPlayerIds.length > 0,
    ...shared,
    /*
      Projections do move, so this branch keeps the poll; the placeholder only keeps the
      previous numbers on screen while a new *id set* loads. Scoped to an unchanged season and
      week on purpose: `keepPreviousData` would also hold last week's points up under this
      week's heading across a rollover, which is worse than a blank — a stale number that reads
      as current. Anything but a fingerprint change starts empty.
    */
    placeholderData: (previous, previousQuery) => {
      const previousKey = previousQuery?.queryKey as
        | readonly unknown[]
        | undefined;
      if (previousKey === undefined) {
        return undefined;
      }
      const scope = boardKeys.playerProjectionsPrefix(season ?? 0, week ?? 0);
      const sameScope = scope.every(
        (segment, index) => previousKey[index] === segment,
      );
      return sameScope ? previous : undefined;
    },
  });

  const boardTeams = useMemo(
    () =>
      joinBoardTeams({
        teams: teams.data ?? [],
        members: members.data ?? [],
        teamSeasonState: state.data ?? [],
        teamWeekProjections: teamProjections.data ?? [],
        teamWeekScores: teamScores.data ?? [],
        rosterHoldings: holdings.data ?? [],
        players: players.data ?? [],
        playerProjections: playerProjections.data ?? [],
        weeklyResults: weeklyResults.data ?? [],
        finalRosters: finalRosters.data ?? [],
        draftPicks: draftPicks.data ?? [],
      }),
    [
      teams.data,
      members.data,
      state.data,
      teamProjections.data,
      teamScores.data,
      holdings.data,
      players.data,
      playerProjections.data,
      weeklyResults.data,
      finalRosters.data,
      draftPicks.data,
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

  // The stamp the header leads with. Folded off the joined teams rather than off the raw rows,
  // so it can only ever name a time that belongs to a team actually on screen.
  const scoresUpdatedAt = useMemo(
    () => newestScoreSyncedAt(boardTeams),
    [boardTeams],
  );

  const sections: [string, { error: Error | null }][] = [
    ["NFL week", nflState],
    ["Season", seasonRow],
    ["Season", latestSeason],
    ["Teams", teams],
    ["Owners", members],
    ["Team state", state],
    ["Projections", teamProjections],
    ["Scores", teamScores],
    ["Rosters", holdings],
    ["Players", players],
    ["Player projections", playerProjections],
    ["Weekly results", weeklyResults],
    ["Final rosters", finalRosters],
    ["Draft", draftPicks],
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
  const isPending =
    nflState.isLoading ||
    seasonRow.isLoading ||
    latestSeason.isLoading ||
    teams.isLoading;

  return {
    season,
    week,
    displayWeek,
    isSeasonFallback,
    isOffRegularSeason,
    seasonId,
    rosterPositions,
    draftPicks: draftPicks.data ?? [],
    memberIdByTeamId,
    teams: boardTeams,
    isPending,
    // No failed query at all, not just no failed teams query. The empty state claims there is
    // nothing to show, which is a different statement from "a request did not come back" — and
    // a failure upstream of teams (nfl_state, or the season lookup) leaves teams merely
    // disabled with a null error, so guarding on teams alone would call a broken board empty.
    isEmpty: !isPending && errors.length === 0 && boardTeams.length === 0,
    errors,
    projectionsUpdatedAt,
    scoresUpdatedAt,
    refetchAll: () => {
      void queryClient.invalidateQueries({ queryKey: boardKeys.all });
    },
  };
}
