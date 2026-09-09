/**
 * The board's TanStack Query keys. A plain module — no components — so the react-refresh rule
 * does not apply.
 *
 * Every key starts with `"board"`, so `invalidateQueries({ queryKey: boardKeys.all })` covers
 * the whole page in one call.
 */
export const boardKeys = {
  all: ["board"] as const,
  nflState: () => ["board", "nfl_state"] as const,
  season: (year: number) => ["board", "seasons", year] as const,
  teams: (seasonId: number) => ["board", "teams", seasonId] as const,
  members: () => ["board", "members"] as const,
  teamSeasonState: (seasonId: number) =>
    ["board", "team_season_state", seasonId] as const,
  teamWeekProjections: (seasonId: number, week: number) =>
    ["board", "team_week_projections", seasonId, week] as const,
  rosterHoldings: (seasonId: number) =>
    ["board", "roster_holdings", seasonId] as const,
  finalRosters: (seasonId: number) => ["board", "final_rosters", seasonId] as const,
  /**
   * Keyed on a fingerprint of the held ids as well as the season. The `.in()` filter is part of
   * the request, so a cache entry keyed on the season alone would keep serving the directory
   * fetched for an older, smaller id set and every newly held or newly frozen player would
   * render as "Unknown player" until something else invalidated the season. This branch is
   * deliberately separate from `rosterHoldings`, which is keyed on the season alone: holdings
   * change (a slot moves) far more often than the set of ids does.
   */
  players: (seasonId: number, heldIdsFingerprint: string) =>
    ["board", "players", seasonId, heldIdsFingerprint] as const,
  /** Keyed on the plain season year — `player_projections` is not league-scoped — plus the ids. */
  playerProjections: (season: number, week: number, heldIdsFingerprint: string) =>
    ["board", "player_projections", season, week, heldIdsFingerprint] as const,
  weeklyResults: (seasonId: number) => ["board", "weekly_results", seasonId] as const,
};

const FNV_OFFSET_BASIS = 0x811c9dc5;
const FNV_PRIME = 0x01000193;
const SEPARATOR = 0x2c; // ","

/**
 * A short, order-independent fingerprint of a set of Sleeper player ids.
 *
 * The held set runs to roughly 360 live ids plus whatever the frozen snapshots still name, so
 * the joined ids themselves would be a two-kilobyte query key that React Query re-hashes on
 * every render. FNV-1a over the sorted ids, with an explicit separator so `["ab", "c"]` and
 * `["a", "bc"]` differ, plus the count as a cheap second signal. This is a cache key, never a
 * security boundary: a collision costs one stale player directory, so 32 bits is plenty.
 */
export function fingerprintIds(ids: readonly string[]): string {
  let hash = FNV_OFFSET_BASIS;
  for (const id of [...ids].sort()) {
    for (let index = 0; index < id.length; index += 1) {
      hash ^= id.charCodeAt(index);
      hash = Math.imul(hash, FNV_PRIME);
    }
    hash ^= SEPARATOR;
    hash = Math.imul(hash, FNV_PRIME);
  }
  return `${ids.length}:${(hash >>> 0).toString(36)}`;
}
