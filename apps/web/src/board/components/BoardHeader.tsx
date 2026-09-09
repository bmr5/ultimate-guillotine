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
  /**
   * True only once the socket has been up and has since gone down. A cold load is not a
   * reconnect, so the page computes this from `hasConnectedOnce && !isConnected` rather than
   * handing the header a bare `isConnected` it would otherwise misread on first paint.
   */
  isReconnecting: boolean;
}

/** Shown in place of the week number before `nfl_state` resolves. */
const UNKNOWN_WEEK_LABEL = "Week —";

/** The header's own label for a dropped socket, beside the week. */
const RECONNECTING_LABEL = "reconnecting";

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
  sortMode,
  onSortModeChange,
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
              className={TOUCH_TARGET_CLASS}
            >
              {SORT_MODE_LABELS[mode]}
            </ToggleGroupItem>
          ))}
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

      {sortFellBack ? (
        <p className="text-xs text-muted-foreground">
          No projections available, so teams are sorted by points for.
        </p>
      ) : null}
    </header>
  );
}
