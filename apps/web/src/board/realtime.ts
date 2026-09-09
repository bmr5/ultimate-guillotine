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

export function backoffDelayMs(attempt: number): number {
  return Math.min(REALTIME_BACKOFF_CAP_MS, 1_000 * 2 ** attempt);
}

export interface RealtimeContext {
  seasonId: number | null;
  season: number | null;
  week: number | null;
}

export type BoardQueryKey = readonly unknown[];

/**
 * `boardKeys.players` and `boardKeys.playerProjections` are keyed on a fingerprint of the held
 * ids, which a Postgres change event does not carry — the new id set only exists once the
 * roster query comes back. Dropping the last segment leaves the prefix every fingerprint
 * variant shares, and `invalidateQueries` matches on prefix, so this reaches all of them.
 */
const FINGERPRINT_PLACEHOLDER = "";

function playersKeyPrefix(seasonId: number): BoardQueryKey {
  return boardKeys.players(seasonId, FINGERPRINT_PLACEHOLDER).slice(0, -1);
}

function playerProjectionsKeyPrefix(season: number, week: number): BoardQueryKey {
  return boardKeys.playerProjections(season, week, FINGERPRINT_PLACEHOLDER).slice(0, -1);
}

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
  // A roster change also changes which players and player projections the board needs.
  return [
    boardKeys.rosterHoldings(seasonId),
    playersKeyPrefix(seasonId),
    playerProjectionsKeyPrefix(season, week),
  ];
}
