import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";

import { ExplainedBadge } from "@/components/explained-badge";
import { badgeVariants } from "@/components/ui/badge-variants";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { REVEAL_CLASS, revealStyle } from "@/motion/reveal";

import {
  crossesMinuteBoundary,
  formatUpdatedAgo,
  formatUpdatedAt,
  formatUpdatedTitle,
  isStale,
  MS_PER_MINUTE,
  PROJECTIONS_PULLED_LABEL,
  SCORES_UPDATED_LABEL,
  STALE_AFTER_MS,
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
  /** The rich / medium / poor split is a view of its own, beside the positions. */
  tiersActive: boolean;
  onTiersChange: (active: boolean) => void;
  sortFellBack: boolean;
  searchTerm: string;
  onSearchTermChange: (term: string) => void;
  /** When the projections were computed — `team_week_projections.computed_at`. */
  projectionsUpdatedAt: number | null;
  /**
   * When the scores were pulled — the newest `team_week_scores.synced_at` for the week, or
   * null when the week has no score row yet.
   *
   * When it exists it is the stamp the header leads with, and the projections stamp drops to a
   * smaller second line. Ben: "why does it show that it updated at 9:30PM it should always be
   * realtime!" — `computed_at` only moves when a projection is recomputed, and leading with it
   * beside a live score would go on making exactly that claim.
   */
  scoresUpdatedAt: number | null;
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

/**
 * Why the season badge is on the header, for its tooltip. `nfl_state` names a season the league
 * has no rows for, so the board is showing the last one it has — which is a finished season,
 * not this week's.
 */
const SEASON_FALLBACK_DESCRIPTION =
  "Sleeper has moved on to a season the league has no data for yet, so this is the last season's final table";

/**
 * Why the stale badge is on the header, for its tooltip, with the threshold read from the one
 * constant the data layer defines it by rather than restated as a number.
 */
const STALE_DESCRIPTION = `Nothing has been pulled from Sleeper for over ${
  STALE_AFTER_MS / MS_PER_MINUTE
} minutes, so these figures may be behind`;

/** Both header badges wear the outline badge face; `ExplainedBadge` supplies the button. */
const HEADER_BADGE_CLASS = badgeVariants({ variant: "outline" });

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
const TIERS_VALUE = "tiers";
const TIERS_LABEL = "Tiers";
const TIERS_ARIA_LABEL = "FAAB tiers: rich, medium and poor";

/**
 * The board's own header: the week, the sort, the search box and the last-pull indicator. It
 * scrolls with the list and wears the same rounded, bordered face as the cards below it at every
 * width — Ben: a pinned header ate half a phone screen, and a full-bleed one with a bare bottom
 * rule looked like a different surface from the cards.
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
  tiersActive,
  onTiersChange,
  sortFellBack,
  searchTerm,
  onSearchTermChange,
  projectionsUpdatedAt,
  scoresUpdatedAt,
  isReconnecting,
}: BoardHeaderProps) {
  /**
   * The stamp the header leads with, and the one everything else about freshness is measured
   * against: the scores when the week has them, the projections otherwise.
   *
   * The scores are the newer of the two by construction — the sync writes `synced_at` every
   * run — so once they exist they are also the honest answer to "is this board stale?".
   */
  const hasScoreStamp = scoresUpdatedAt !== null;
  const primaryUpdatedAt = hasScoreStamp
    ? scoresUpdatedAt
    : projectionsUpdatedAt;
  const primaryLabel = hasScoreStamp ? SCORES_UPDATED_LABEL : undefined;

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
    primaryUpdatedAt === null ? 0 : Math.max(0, now - primaryUpdatedAt);
  useEffect(() => {
    const previousElapsed = previousElapsedRef.current;
    previousElapsedRef.current = elapsed;
    if (previousElapsed === null) {
      return;
    }
    if (crossesMinuteBoundary(previousElapsed, elapsed)) {
      setAnnounced(
        `${formatUpdatedAt(
          primaryUpdatedAt,
          now,
          {},
          primaryLabel,
        )}, ${formatUpdatedAgo(primaryUpdatedAt, now)}`,
      );
    }
  }, [elapsed, primaryUpdatedAt, primaryLabel, now]);

  const stale = isStale(primaryUpdatedAt, now);

  return (
    <header
      className={`mb-3 space-y-2 rounded-xl border bg-background/70 px-4 py-3 backdrop-blur-md ${REVEAL_CLASS}`}
      // The first thing on the board to settle; the cards follow it down the page.
      style={revealStyle(0)}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        {/* The site title lives in the layout; this header names the week only. */}
        <h2 className="text-2xl leading-none figures">
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
          data-stamp={hasScoreStamp ? "scores" : "projections"}
          className="text-sm text-muted-foreground"
          title={formatUpdatedTitle(primaryUpdatedAt, {}, primaryLabel)}
          aria-hidden="true"
        >
          {formatUpdatedAt(primaryUpdatedAt, now, {}, primaryLabel)}
        </span>
        <span className="text-xs text-muted-foreground/80" aria-hidden="true">
          {formatUpdatedAgo(primaryUpdatedAt, now)}
        </span>
        {isSeasonFallback ? (
          <ExplainedBadge
            description={SEASON_FALLBACK_DESCRIPTION}
            className={HEADER_BADGE_CLASS}
          >
            {seasonFallbackLabel(season)}
          </ExplainedBadge>
        ) : null}
        {stale ? (
          <ExplainedBadge
            description={STALE_DESCRIPTION}
            className={HEADER_BADGE_CLASS}
          >
            Stale data
          </ExplainedBadge>
        ) : null}
        {isReconnecting ? (
          <span className="text-xs text-muted-foreground">
            {RECONNECTING_LABEL}
          </span>
        ) : null}
      </div>

      {/*
        The projections stamp, kept as a smaller second line once the scores lead. Two figures
        sit side by side on every card and they are pulled on different clocks — the scores
        every minute in a game window, the projections every five — so one stamp cannot
        truthfully describe both. Dropped entirely when there is no score row: the line above
        is then already the projections stamp, and repeating it would say the same thing twice.

        `aria-hidden` for the same reason as the two spans above: the live region below is the
        one thing a screen reader should hear about freshness, and it speaks on minute
        boundaries. A second unhidden timestamp would be read out on every render instead.
      */}
      {hasScoreStamp ? (
        <p
          data-projection-stamp
          className="text-xs text-muted-foreground/80"
          aria-hidden="true"
          title={formatUpdatedTitle(
            projectionsUpdatedAt,
            {},
            PROJECTIONS_PULLED_LABEL,
          )}
        >
          {formatUpdatedAt(
            projectionsUpdatedAt,
            now,
            {},
            PROJECTIONS_PULLED_LABEL,
          )}
        </p>
      ) : null}

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
        value={
          tiersActive ? TIERS_VALUE : (positionFilter ?? ALL_POSITIONS_VALUE)
        }
        onValueChange={(value) => {
          // Radix hands back "" when the active item is clicked again; the board is always in
          // exactly one of these states, so that is a no-op rather than an eighth one.
          if (value === TIERS_VALUE) {
            onTiersChange(true);
          } else if (value !== "") {
            onTiersChange(false);
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
        {/* Ben (2026-09-10): "a fun filter that splits the rosters into tiers of rich medium
            poor with math". It sits with the positions because it is the same gesture: a
            different way to read the whole league. */}
        <ToggleGroupItem
          value={TIERS_VALUE}
          aria-label={TIERS_ARIA_LABEL}
          className={TOUCH_TARGET_CLASS}
        >
          {TIERS_LABEL}
        </ToggleGroupItem>
      </ToggleGroup>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        {tiersActive ? null : (
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
        )}

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
