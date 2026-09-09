import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { BoardHeader } from "@/board/components/BoardHeader";
import {
  BoardEmpty,
  BoardErrors,
  BoardSkeleton,
  EliminatedDivider,
  RealtimeBanner,
} from "@/board/components/BoardStates";
import { TeamCard } from "@/board/components/TeamCard";
import { filterTeams } from "@/board/derive/search";
import { selectEffectiveSortMode, sortBoardTeams } from "@/board/derive/sort";
import { REALTIME_POLL_MS } from "@/board/realtime";
import { parseSortMode, type SortMode } from "@/board/types";
import { useBoardData } from "@/board/useBoardData";
import { useDebouncedValue } from "@/board/useDebouncedValue";
import { useLeagueBoardRealtime } from "@/board/useLeagueBoardRealtime";

const GRID = "grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3";

/** The URL parameter the sort is shared through. */
const SORT_PARAM = "sort";

/** Long enough that a typed word settles into one derivation, short enough to feel immediate. */
const SEARCH_DEBOUNCE_MS = 150;

/** Named once, here, and nowhere else on the board — Ben's decision 2. */
const PROJECTION_SOURCE_LINE = "Projections: Sleeper";

export function BoardPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedSort = parseSortMode(searchParams.get(SORT_PARAM));

  const [rawSearch, setRawSearch] = useState("");
  const searchTerm = useDebouncedValue(rawSearch, SEARCH_DEBOUNCE_MS);
  /**
   * A team's card is open when the search auto-expanded it — unless the reader has since said
   * otherwise about that team, which is what this map records.
   *
   * A plain "explicitly opened" set cannot express the case the reader hits first: a search that
   * auto-expands a card leaves the card open no matter what the set says, so tapping it does
   * nothing and the roster cannot be put away. `false` here is a real, storable answer, so an
   * auto-expanded card closes on the first tap and opens again on the second.
   */
  const [openOverrides, setOpenOverrides] = useState<
    ReadonlyMap<number, boolean>
  >(() => new Map());

  /**
   * The poll is only the fallback for a dead socket, so it is derived from the socket's own
   * `isConnected` and never from a second connection flag. `useBoardData` has to be called
   * before `useLeagueBoardRealtime` — the subscription is scoped by the season the data hook
   * resolves — so the value is fed back through one state update on the render after the
   * connection flips. A stale poll for a single render costs nothing; two flags that can
   * disagree would.
   */
  const [pollingMs, setPollingMs] = useState<number | false>(REALTIME_POLL_MS);

  const board = useBoardData({ pollingMs });

  const realtime = useLeagueBoardRealtime({
    seasonId: board.seasonId,
    season: board.season,
    week: board.week,
  });

  const nextPollingMs = realtime.isConnected ? false : REALTIME_POLL_MS;
  useEffect(() => {
    setPollingMs(nextPollingMs);
  }, [nextPollingMs]);

  /*
    Every derived list below is memoized, and `TeamCard` is memoized on its props. A refetch of
    a query the cards do not read — `nfl_state` is the frequent one, and it polls on its own —
    hands back an identical `board.teams` reference, so these all skip and not one card
    re-renders. The header's own per-second clock is local to the header for the same reason.
  */
  const filtered = useMemo(
    () => filterTeams(board.teams, searchTerm),
    [board.teams, searchTerm],
  );

  const effective = useMemo(
    () => selectEffectiveSortMode(filtered.teams, requestedSort),
    [filtered.teams, requestedSort],
  );

  const sorted = useMemo(
    () => sortBoardTeams(filtered.teams, effective.mode),
    [filtered.teams, effective.mode],
  );

  const autoExpanded = useMemo(
    () => new Set(filtered.autoExpandTeamIds),
    [filtered.autoExpandTeamIds],
  );

  /**
   * The toggle has to know whether the card it is closing was auto-expanded, but it must stay
   * referentially stable across a search — it is a prop on every memoized `TeamCard`, and a new
   * identity on every keystroke would re-render the whole board. A ref carries the current
   * auto-expand set into a callback that depends on nothing.
   */
  const autoExpandedRef = useRef(autoExpanded);
  autoExpandedRef.current = autoExpanded;

  const handleToggle = useCallback((teamId: number) => {
    setOpenOverrides((current) => {
      const wasOpen =
        current.get(teamId) ?? autoExpandedRef.current.has(teamId);
      const next = new Map(current);
      next.set(teamId, !wasOpen);
      return next;
    });
  }, []);

  const handleSortModeChange = useCallback(
    (mode: SortMode) => {
      // Sort lives in the URL so a member can share the view they are looking at.
      const next = new URLSearchParams(searchParams);
      next.set(SORT_PARAM, mode);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const isOpen = (teamId: number) =>
    openOverrides.get(teamId) ?? autoExpanded.has(teamId);

  const showList = !board.isPending && !board.isEmpty;

  /**
   * A cold load is not a dropped socket: `isConnected` is false for every board's first paint,
   * so gating the paused banner and the header's "reconnecting" label on it alone flashed both
   * on every single visit. They appear only once the socket has been up and has since gone
   * down — the only state either of them describes truthfully.
   */
  const isReconnecting = realtime.hasConnectedOnce && !realtime.isConnected;

  return (
    <main className="px-4 pb-10 sm:px-0">
      <BoardHeader
        week={board.week}
        sortMode={requestedSort}
        onSortModeChange={handleSortModeChange}
        sortFellBack={effective.fellBack}
        searchTerm={rawSearch}
        onSearchTermChange={setRawSearch}
        projectionsUpdatedAt={board.projectionsUpdatedAt}
        isReconnecting={isReconnecting}
      />

      <div className="space-y-3">
        {isReconnecting ? (
          // `refreshNow`, not `refetchAll`: the button also rebuilds the channel, which is the
          // only way to skip a pending backoff timer.
          <RealtimeBanner onRefresh={realtime.refreshNow} />
        ) : null}

        <BoardErrors errors={board.errors} onRetry={board.refetchAll} />

        {board.isPending ? <BoardSkeleton /> : null}
        {!board.isPending && board.isEmpty ? <BoardEmpty /> : null}

        {showList ? (
          <>
            <ul className={GRID}>
              {sorted.active.map((team, index) => (
                <TeamCard
                  key={team.teamId}
                  team={team}
                  rank={index + 1}
                  isOpen={isOpen(team.teamId)}
                  onToggle={handleToggle}
                  highlightedPlayerIds={filtered.matchedPlayerIds}
                />
              ))}
            </ul>

            {sorted.eliminated.length > 0 ? (
              <>
                <EliminatedDivider count={sorted.eliminated.length} />
                <ul className={GRID}>
                  {sorted.eliminated.map((team, index) => (
                    <TeamCard
                      key={team.teamId}
                      team={team}
                      rank={sorted.active.length + index + 1}
                      isOpen={isOpen(team.teamId)}
                      onToggle={handleToggle}
                      highlightedPlayerIds={filtered.matchedPlayerIds}
                    />
                  ))}
                </ul>
              </>
            ) : null}
          </>
        ) : null}
      </div>

      {/*
        The only place the projection provider is named. Ben's decision 2 replaced the
        per-card and per-header disclaimers with this one line.
      */}
      <footer className="mt-6 text-xs text-muted-foreground">
        {PROJECTION_SOURCE_LINE}
      </footer>
    </main>
  );
}
