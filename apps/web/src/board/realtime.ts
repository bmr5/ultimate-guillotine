import { boardKeys } from "./queryKeys";

/**
 * The published tables the board subscribes to. The data layer also publishes
 * `final_rosters`, which the board deliberately leaves off this list (Spec issue 11): a
 * snapshot lands in the same transaction as the `team_season_state` change that flips
 * `is_eliminated`, and `keysForTable` already invalidates the snapshot query from there.
 * public.player_projections is not published at all — a run touches thousands of rows — so
 * that branch relies on the REALTIME_POLL_MS poll and on roster changes to refresh it.
 */
export const BOARD_REALTIME_TABLES = [
  "roster_holdings",
  "team_season_state",
  "team_week_projections",
  "nfl_state",
] as const;

export type BoardRealtimeTable = (typeof BOARD_REALTIME_TABLES)[number];

export const REALTIME_DEBOUNCE_MS = 750;
/**
 * The trailing debounce restarts on every event, so a sync job writing steadily just under the
 * debounce could hold the refetch off indefinitely. This is the ceiling on that wait: once the
 * first event of a burst is this old, the queue flushes whether or not events are still landing.
 */
export const REALTIME_MAX_WAIT_MS = 3_000;
/** Beyond this many events in one window, collapse into a single whole-board refetch. */
export const REALTIME_MAX_EVENTS_PER_BURST = 18;
export const REALTIME_BACKOFF_CAP_MS = 30_000;
export const REALTIME_POLL_MS = 60_000;
/**
 * Every open board reconnects on the same schedule after a shared outage, so an undithered
 * backoff would send the whole league at the socket in one wave. The delay is scaled by a
 * factor in [0.8, 1.2) to spread them out.
 */
export const REALTIME_BACKOFF_JITTER_MIN = 0.8;
export const REALTIME_BACKOFF_JITTER_MAX = 1.2;

/**
 * The exponential base is capped first and the jitter applied after, so the spread survives at
 * the cap — which is exactly where a synchronised herd would otherwise be worst. An actual
 * delay therefore ranges over [24_000, 36_000) ms once the cap is reached.
 *
 * `random` is injectable so tests get a fixed delay instead of a range.
 */
export function backoffDelayMs(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(REALTIME_BACKOFF_CAP_MS, 1_000 * 2 ** attempt);
  const jitterSpan = REALTIME_BACKOFF_JITTER_MAX - REALTIME_BACKOFF_JITTER_MIN;
  return Math.round(base * (REALTIME_BACKOFF_JITTER_MIN + jitterSpan * random()));
}

export interface RealtimeContext {
  seasonId: number | null;
  season: number | null;
  week: number | null;
}

export type BoardQueryKey = readonly unknown[];

export function keysForTable(
  table: BoardRealtimeTable,
  context: RealtimeContext,
): readonly BoardQueryKey[] {
  const { seasonId, season, week } = context;
  if (table === "nfl_state" || seasonId === null || season === null || week === null) {
    return [boardKeys.all];
  }
  if (table === "team_season_state") {
    // An elimination flips is_eliminated here and writes the final_rosters snapshot in the
    // same transaction; the board does not subscribe to final_rosters, so pull it from here.
    return [boardKeys.teamSeasonState(seasonId), boardKeys.finalRosters(seasonId)];
  }
  if (table === "team_week_projections") {
    return [boardKeys.teamWeekProjections(seasonId, week)];
  }
  // A roster change also changes which player projections the board needs. The static player
  // directory is deliberately not invalidated: it is keyed on a fingerprint of the held ids, so
  // a change to that set already produces a different key and a fresh fetch, while a holding
  // that merely moves between teams leaves the id set — and therefore the directory — alone.
  // The projections key is the fingerprintless prefix, since the event does not carry the ids.
  return [
    boardKeys.rosterHoldings(seasonId),
    boardKeys.playerProjectionsPrefix(season, week),
  ];
}
