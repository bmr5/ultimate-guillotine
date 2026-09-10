import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";

import { BoardHeader } from "@/board/components/BoardHeader";
import {
  BoardEmpty,
  BoardErrors,
  BoardSkeleton,
  EliminatedDivider,
  RealtimeBanner,
} from "@/board/components/BoardStates";
import { PositionView } from "@/board/components/PositionView";
import { TeamCard } from "@/board/components/TeamCard";
import { positionView } from "@/board/derive/position";
import { resolveCardEmphasis } from "@/board/derive/score";
import { filterTeams } from "@/board/derive/search";
import { selectEffectiveSortMode, sortBoardTeams } from "@/board/derive/sort";
import { BOARD_GRID, BOARD_WIDTH } from "@/board/layout";
import { REALTIME_POLL_MS } from "@/board/realtime";
import {
  parsePositionFilter,
  parsePositionSortMode,
  parseSortMode,
  type PositionFilter,
  type SortMode,
} from "@/board/types";
import { useBoardData } from "@/board/useBoardData";
import { useDebouncedValue } from "@/board/useDebouncedValue";
import { useLeagueBoardRealtime } from "@/board/useLeagueBoardRealtime";

/** The URL parameter the sort is shared through. */
const SORT_PARAM = "sort";

/** The URL parameter the position quick view is shared through; absent means the whole board. */
const POSITION_PARAM = "pos";

/** Long enough that a typed word settles into one derivation, short enough to feel immediate. */
const SEARCH_DEBOUNCE_MS = 150;

/** Named once, here, and nowhere else on the board — Ben's decision 2. */
const PROJECTION_SOURCE_LINE = "Projections: Sleeper";

export function BoardPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const positionFilter = parsePositionFilter(searchParams.get(POSITION_PARAM));
  /**
   * The position view offers two of the three sorts and defaults to FAAB rather than to the
   * board's own default, so `?sort=points_for` carried into a position view reads as FAAB and
   * is still there — untouched in the URL — when the reader goes back to the whole board.
   */
  const requestedSort =
    positionFilter === null
      ? parseSortMode(searchParams.get(SORT_PARAM))
      : parsePositionSortMode(searchParams.get(SORT_PARAM));

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
    // The one-render feedback described above `pollingMs`: the hook that owns the answer runs
    // after the hook that needs it, so a state update is the only way back.
    // eslint-disable-next-line react-hooks/set-state-in-effect
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

  const positionRows = useMemo(
    () =>
      positionFilter === null
        ? []
        : positionView(
            filtered.teams,
            positionFilter,
            board.rosterPositions,
            requestedSort,
          ),
    [filtered.teams, positionFilter, board.rosterPositions, requestedSort],
  );

  /**
   * Which figure the cards emphasise, decided once for the whole board rather than per card.
   *
   * Off `board.teams`, not `filtered.teams`: a search that narrows the board to one scoreless
   * team must not flip every visible card back to projection emphasis mid-Sunday. The question
   * is what the week is doing, and that does not change because somebody typed a name.
   */
  const emphasis = useMemo(
    () => resolveCardEmphasis(board.teams),
    [board.teams],
  );

  const autoExpanded = useMemo(
    () => new Set(filtered.autoExpandTeamIds),
    [filtered.autoExpandTeamIds],
  );

  /**
   * The toggle has to know whether the card it is closing was auto-expanded, but it must stay
   * referentially stable across a search — it is a prop on every memoized `TeamCard`, and a new
   * identity on every keystroke would re-render the whole board. A ref carries the current
   * auto-expand set into a callback that depends on nothing. The ref is written from an effect,
   * the one place React allows, and the toggle is a click handler, so it always runs after.
   */
  const autoExpandedRef = useRef(autoExpanded);
  useEffect(() => {
    autoExpandedRef.current = autoExpanded;
  }, [autoExpanded]);

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

  const handlePositionFilterChange = useCallback(
    (position: PositionFilter | null) => {
      const next = new URLSearchParams(searchParams);
      // Absent, never `?pos=all`: the whole board is the parameter's absence, not a value.
      if (position === null) {
        next.delete(POSITION_PARAM);
      } else {
        next.set(POSITION_PARAM, position);
      }
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
    <main className={`${BOARD_WIDTH} px-4 pb-10 sm:px-0`}>
      <BoardHeader
        // The header names `display_week`; `board.week` is what the numbers are scoped to, and
        // outside the regular season the two are different weeks.
        week={board.displayWeek}
        season={board.season}
        isSeasonFallback={board.isSeasonFallback}
        scopedWeek={board.week}
        isOffRegularSeason={board.isOffRegularSeason}
        sortMode={requestedSort}
        onSortModeChange={handleSortModeChange}
        positionFilter={positionFilter}
        onPositionFilterChange={handlePositionFilterChange}
        // The fallback is about the board's own projection sort; a position view never asks
        // for points for, so the sentence would be answering a question nobody asked.
        sortFellBack={positionFilter === null && effective.fellBack}
        searchTerm={rawSearch}
        onSearchTermChange={setRawSearch}
        projectionsUpdatedAt={board.projectionsUpdatedAt}
        scoresUpdatedAt={board.scoresUpdatedAt}
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

        {showList && positionFilter !== null ? (
          <PositionView
            position={positionFilter}
            rows={positionRows}
            isOpen={isOpen}
            onToggle={handleToggle}
            highlightedPlayerIds={filtered.matchedPlayerIds}
            rosterPositions={board.rosterPositions}
          />
        ) : null}

        {showList && positionFilter === null ? (
          <>
            <ul className={BOARD_GRID}>
              {sorted.active.map((team, index) => (
                <TeamCard
                  key={team.teamId}
                  team={team}
                  rank={index + 1}
                  isOpen={isOpen(team.teamId)}
                  onToggle={handleToggle}
                  highlightedPlayerIds={filtered.matchedPlayerIds}
                  rosterPositions={board.rosterPositions}
                  emphasis={emphasis}
                />
              ))}
            </ul>

            {sorted.eliminated.length > 0 ? (
              <>
                <EliminatedDivider
                  count={sorted.eliminated.length}
                  // The place after the last active card, so the rule settles in with the list.
                  revealIndex={sorted.active.length + 1}
                />
                <ul className={BOARD_GRID}>
                  {sorted.eliminated.map((team, index) => (
                    <TeamCard
                      key={team.teamId}
                      team={team}
                      rank={sorted.active.length + index + 1}
                      isOpen={isOpen(team.teamId)}
                      onToggle={handleToggle}
                      highlightedPlayerIds={filtered.matchedPlayerIds}
                      rosterPositions={board.rosterPositions}
                      emphasis={emphasis}
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
