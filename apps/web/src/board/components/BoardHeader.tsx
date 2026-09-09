import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

import {
  crossesMinuteBoundary,
  formatUpdatedAgo,
  formatUpdatedAt,
  formatUpdatedTitle,
  isStale,
  TICK_INTERVAL_MS,
} from "../derive/time";
import {
  ALL_POSITIONS_LABEL,
  ALL_POSITIONS_VALUE,
  POSITION_FILTERS,
  POSITION_SORT_MODES,
  SORT_MODE_LABELS,
  SORT_MODES,
  type PositionFilter,
  type SortMode,
} from "../types";

interface BoardHeaderProps {
  /** The week this header names — `display_week` once the regular season is over. */
  week: number | null;
  /** The year of the `seasons` row on screen; only labelled when it is a fallback. */
  season: number | null;
  /** True when `nfl_state` has rolled to a year the league has no season row for. */
  isSeasonFallback: boolean;
  /** The week the numbers below are actually scoped to; see `scopedWeek` in the caveat. */
  scopedWeek: number | null;
  /** True when `nfl_state.season_type` is anything but `regular`. */
  isOffRegularSeason: boolean;
  sortMode: SortMode;
  onSortModeChange: (mode: SortMode) => void;
  /** The position the board is narrowed to, or null for every team's whole roster. */
  positionFilter: PositionFilter | null;
  onPositionFilterChange: (position: PositionFilter | null) => void;
  sortFellBack: boolean;
  searchTerm: string;
  onSearchTermChange: (term: string) => void;
  /** When the projections were pulled — `team_week_projections.computed_at`. */
  projectionsUpdatedAt: number | null;
  /**
   * True only once the socket has been up and has since gone down. A cold load is not a
   * reconnect, so the page computes this from `hasConnectedOnce && !isConnected` rather than
   * handing the header a bare `isConnected` it would otherwise misread on first paint.
   */
  isReconnecting: boolean;
}

/** Shown in place of the week number before `nfl_state` resolves. */
const UNKNOWN_WEEK_LABEL = "Week —";

/**
 * The season badge shown when `nfl_state` has rolled past the last season the league has a row
 * for: without it an offseason board silently reads as if last season's final table were live.
 */
function seasonFallbackLabel(season: number | null): string {
  return season === null ? "Final season" : `Season ${season} (final)`;
}

/** The header's own label for a dropped socket, beside the week. */
const RECONNECTING_LABEL = "reconnecting";

/** What the position segments are for, said once for a reader who cannot see the row. */
const POSITION_FILTER_LABEL = "Show one position across the league";

/** The "no filter" segment's own label; the visible text is just `All`. */
const ALL_POSITIONS_ARIA_LABEL = "All positions";

/** One label for the search box and its clear button, so the two cannot drift apart. */
const SEARCH_LABEL = "Search owner, team, or player";
const CLEAR_SEARCH_LABEL = "Clear search";

/**
 * The 44px floor every control in this header sits on. The sort toggles and the search box are
 * the two things a member taps on a phone while scrolling a live board, and the `sm` toggle
 * variant and the `h-10` input both land under the floor on their own.
 */
const TOUCH_TARGET_CLASS = "min-h-[44px]";

/**
 * The board's own header: the week, the sort, the search box and the last-pull indicator. It is
 * sticky but never collapses — a header that changes height as the list scrolls moves the sort
 * and search controls out from under the reader's finger mid-scroll.
 *
 * Every second-by-second tick lives here rather than in the page, so the clock re-renders this
 * header alone and never the team cards below it.
 */
export function BoardHeader({
  week,
  season,
  isSeasonFallback,
  scopedWeek,
  isOffRegularSeason,
  sortMode,
  onSortModeChange,
  positionFilter,
  onPositionFilterChange,
  sortFellBack,
  searchTerm,
  onSearchTermChange,
  projectionsUpdatedAt,
  isReconnecting,
}: BoardHeaderProps) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(
      () => setNow(Date.now()),
      TICK_INTERVAL_MS,
    );
    return () => window.clearInterval(timer);
  }, []);

  // The indicator ticks every second but only announces on a minute boundary: see
  // `crossesMinuteBoundary` for why a per-second announcement is worse than none.
  const [announced, setAnnounced] = useState("");
  /**
   * Seeded lazily rather than at zero. A board opened onto an hour-old pull starts with a large
   * elapsed, and a ref seeded at `0` would read that first render as a minute boundary and
   * announce the pull time to a reader who has only just arrived — the one moment the header
   * has nothing new to say. `null` means "no previous tick", and the first run only records.
   */
  const previousElapsedRef = useRef<number | null>(null);
  const elapsed =
    projectionsUpdatedAt === null ? 0 : Math.max(0, now - projectionsUpdatedAt);
  useEffect(() => {
    const previousElapsed = previousElapsedRef.current;
    previousElapsedRef.current = elapsed;
    if (previousElapsed === null) {
      return;
    }
    if (crossesMinuteBoundary(previousElapsed, elapsed)) {
      setAnnounced(
        `${formatUpdatedAt(projectionsUpdatedAt, now)}, ${formatUpdatedAgo(
          projectionsUpdatedAt,
          now,
        )}`,
      );
    }
  }, [elapsed, projectionsUpdatedAt, now]);

  const stale = isStale(projectionsUpdatedAt, now);

  return (
    <header className="sticky top-0 z-20 -mx-4 mb-3 space-y-2 border-b bg-background/95 px-4 py-3 backdrop-blur sm:mx-0 sm:px-0">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        {/* The site title lives in the layout; this header names the week only. */}
        <h2 className="text-lg font-semibold">
          {week === null ? UNKNOWN_WEEK_LABEL : `Week ${week}`}
        </h2>
        {/*
          Ben's decision 2: the absolute pull time in the viewer's own timezone leads, the
          relative form follows as smaller secondary text, and no provider wording appears
          here at all — the provider is named once in the page footer.

          Both spans are aria-hidden because the live region below is the one thing a screen
          reader should hear about the pull time, and it speaks only on minute boundaries.
        */}
        <span
          className="text-sm text-muted-foreground"
          title={formatUpdatedTitle(projectionsUpdatedAt)}
          aria-hidden="true"
        >
          {formatUpdatedAt(projectionsUpdatedAt, now)}
        </span>
        <span className="text-xs text-muted-foreground/80" aria-hidden="true">
          {formatUpdatedAgo(projectionsUpdatedAt, now)}
        </span>
        {isSeasonFallback ? (
          <Badge variant="outline">{seasonFallbackLabel(season)}</Badge>
        ) : null}
        {stale ? <Badge variant="outline">Stale data</Badge> : null}
        {isReconnecting ? (
          <span className="text-xs text-muted-foreground">
            {RECONNECTING_LABEL}
          </span>
        ) : null}
      </div>

      <p className="sr-only" aria-live="polite">
        {announced}
      </p>

      {/*
        Ben's addendum 2: one position across the whole league, in one tap. Wrapping rather than
        scrolling, because seven 44px segments do not fit across a phone in one line and a row
        that scrolls sideways hides its own last segment.
      */}
      <ToggleGroup
        type="single"
        value={positionFilter ?? ALL_POSITIONS_VALUE}
        onValueChange={(value) => {
          // Radix hands back "" when the active item is clicked again; the board is always in
          // exactly one of these states, so that is a no-op rather than an eighth one.
          if (value !== "") {
            onPositionFilterChange(
              value === ALL_POSITIONS_VALUE ? null : (value as PositionFilter),
            );
          }
        }}
        aria-label={POSITION_FILTER_LABEL}
        variant="outline"
        size="sm"
        className="flex-wrap justify-start"
      >
        <ToggleGroupItem
          value={ALL_POSITIONS_VALUE}
          aria-label={ALL_POSITIONS_ARIA_LABEL}
          className={TOUCH_TARGET_CLASS}
        >
          {ALL_POSITIONS_LABEL}
        </ToggleGroupItem>
        {POSITION_FILTERS.map((position) => (
          <ToggleGroupItem
            key={position}
            value={position}
            aria-label={position}
            className={TOUCH_TARGET_CLASS}
          >
            {position}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <ToggleGroup
          type="single"
          value={sortMode}
          onValueChange={(value) => {
            // Radix hands back "" when the active item is clicked again; the board always has
            // exactly one sort, so that is a no-op rather than a fourth state.
            if (value !== "") {
              onSortModeChange(value as SortMode);
            }
          }}
          aria-label="Sort teams by"
          variant="outline"
          size="sm"
        >
          {/*
            A position view answers "who can bid and who needs one", so it offers the two sorts
            that speak to that and drops the season total, which speaks to neither.
          */}
          {(positionFilter === null ? SORT_MODES : POSITION_SORT_MODES).map(
            (mode) => (
              <ToggleGroupItem
                key={mode}
                value={mode}
                aria-label={SORT_MODE_LABELS[mode]}
                className={TOUCH_TARGET_CLASS}
              >
                {SORT_MODE_LABELS[mode]}
              </ToggleGroupItem>
            ),
          )}
        </ToggleGroup>

        <div className="flex items-center gap-2 sm:w-auto">
          <Input
            type="search"
            value={searchTerm}
            onChange={(event) => onSearchTermChange(event.target.value)}
            placeholder={SEARCH_LABEL}
            aria-label={SEARCH_LABEL}
            className={`${TOUCH_TARGET_CLASS} sm:w-64`}
          />
          {/*
            An explicit clear button, rendered only when there is something to clear. The `x`
            some browsers put inside `type="search"` is not on any of them — mobile Safari and
            Firefox render none — so without this the only way back to the full board on a phone
            is to hold backspace.
          */}
          {searchTerm === "" ? null : (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={CLEAR_SEARCH_LABEL}
              onClick={() => onSearchTermChange("")}
              className={`${TOUCH_TARGET_CLASS} min-w-[44px] shrink-0`}
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </Button>
          )}
        </div>
      </div>

      {/*
        Outside the regular season `nfl_state.week` names a week this league never played, so
        the numbers come from the last week that has results. Saying so is the difference
        between a final table and one that looks stale for no stated reason.

        Season-neutral wording: `season_type` is anything but `regular` in the preseason too,
        and "Regular season complete" is a lie in August. The sentence states what the board is
        showing and why, which is true in every phase this branch is reachable in.
      */}
      {isOffRegularSeason && scopedWeek !== null && scopedWeek !== week ? (
        <p className="text-xs text-muted-foreground">
          {`Showing week ${scopedWeek}, the last week with final results.`}
        </p>
      ) : null}

      {sortFellBack ? (
        <p className="text-xs text-muted-foreground">
          No projections available, so teams are sorted by total points.
        </p>
      ) : null}
    </header>
  );
}
