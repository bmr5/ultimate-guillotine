import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
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
import { SORT_MODE_LABELS, SORT_MODES, type SortMode } from "../types";

interface BoardHeaderProps {
  week: number | null;
  sortMode: SortMode;
  onSortModeChange: (mode: SortMode) => void;
  sortFellBack: boolean;
  searchTerm: string;
  onSearchTermChange: (term: string) => void;
  /** When the projections were pulled — `team_week_projections.computed_at`. */
  projectionsUpdatedAt: number | null;
  isRealtimeConnected: boolean;
}

/** Shown in place of the week number before `nfl_state` resolves. */
const UNKNOWN_WEEK_LABEL = "Week —";

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
  sortMode,
  onSortModeChange,
  sortFellBack,
  searchTerm,
  onSearchTermChange,
  projectionsUpdatedAt,
  isRealtimeConnected,
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
  const previousElapsedRef = useRef(0);
  const elapsed =
    projectionsUpdatedAt === null ? 0 : Math.max(0, now - projectionsUpdatedAt);
  useEffect(() => {
    if (crossesMinuteBoundary(previousElapsedRef.current, elapsed)) {
      setAnnounced(
        `${formatUpdatedAt(projectionsUpdatedAt, now)}, ${formatUpdatedAgo(projectionsUpdatedAt, now)}`,
      );
    }
    previousElapsedRef.current = elapsed;
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
        {stale ? <Badge variant="outline">Stale data</Badge> : null}
        {!isRealtimeConnected ? (
          <span className="text-xs text-muted-foreground">reconnecting</span>
        ) : null}
      </div>

      <p className="sr-only" aria-live="polite">
        {announced}
      </p>

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
          {SORT_MODES.map((mode) => (
            <ToggleGroupItem
              key={mode}
              value={mode}
              aria-label={SORT_MODE_LABELS[mode]}
            >
              {SORT_MODE_LABELS[mode]}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>

        <Input
          type="search"
          value={searchTerm}
          onChange={(event) => onSearchTermChange(event.target.value)}
          placeholder="Search owner, team, or player"
          aria-label="Search owner, team, or player"
          className="sm:max-w-xs"
        />
      </div>

      {sortFellBack ? (
        <p className="text-xs text-muted-foreground">
          No projections available, so teams are sorted by points for.
        </p>
      ) : null}
    </header>
  );
}
