import type { SupabaseClient } from "@supabase/supabase-js";

import type { Database, TableRow } from "./types";

export type BoardClient = SupabaseClient<Database>;

export type NflStateRow = Pick<
  TableRow<"nfl_state">,
  "id" | "season" | "season_type" | "week" | "display_week" | "synced_at"
>;
export type SeasonRow = TableRow<"seasons">;
export type TeamRow = Pick<
  TableRow<"teams">,
  "id" | "sleeper_roster_id" | "team_name" | "member_id"
>;
export type MemberRow = Pick<
  TableRow<"members">,
  "id" | "sleeper_display_name" | "nickname"
>;
export type TeamSeasonStateRow = TableRow<"team_season_state">;
export type TeamWeekProjectionRow = TableRow<"team_week_projections">;
export type RosterHoldingRow = Pick<
  TableRow<"roster_holdings">,
  "team_id" | "sleeper_player_id" | "slot" | "slot_index" | "lineup_position"
>;
export type PlayerRow = Pick<
  TableRow<"players">,
  "sleeper_player_id" | "full_name" | "position" | "team"
>;
export type PlayerProjectionRow = Pick<
  TableRow<"player_projections">,
  "sleeper_player_id" | "league_points"
>;
export type WeeklyResultFetchRow = Pick<
  TableRow<"weekly_results">,
  "week" | "team_id" | "points" | "is_final" | "state_version"
>;
export type FinalRosterRow = Pick<
  TableRow<"final_rosters">,
  "team_id" | "eliminated_week" | "holdings" | "frozen_at"
>;

interface SupabaseResult<T> {
  data: T[] | null;
  error: { message: string } | null;
}

/**
 * How many ids one `.in(...)` filter may carry.
 *
 * PostgREST renders `.in()` into the query string, so the whole id list travels in the URL. The
 * live set is already ~360 ids and every frozen `final_rosters` snapshot only adds to it, so an
 * unchunked list grows past the proxy's URL limit somewhere mid-season and the request starts
 * failing with a 414 rather than degrading. 150 six-character ids is roughly a kilobyte of
 * query string — comfortably inside every limit in the path, and few enough batches that the
 * round trips stay parallel.
 */
export const IN_CHUNK_SIZE = 150;

/**
 * Split an id list into `.in(...)`-sized batches. Exported because `/trades` reads the same
 * `public.players` table through the same URL-length limit — one chunking rule for both pages.
 */
export function chunkIds(ids: readonly string[]): string[][] {
  const batches: string[][] = [];
  for (let start = 0; start < ids.length; start += IN_CHUNK_SIZE) {
    batches.push(ids.slice(start, start + IN_CHUNK_SIZE));
  }
  return batches;
}

async function unwrap<T>(
  query: PromiseLike<SupabaseResult<T>>,
  label: string,
): Promise<T[]> {
  const { data, error } = await query;
  if (error !== null) {
    throw new Error(`${label}: ${error.message}`);
  }
  return data ?? [];
}

export async function fetchNflState(
  client: BoardClient,
): Promise<NflStateRow | null> {
  const rows = await unwrap<NflStateRow>(
    client
      .from("nfl_state")
      .select("id, season, season_type, week, display_week, synced_at")
      .eq("id", 1),
    "nfl_state",
  );
  return rows[0] ?? null;
}

export async function fetchSeasonByYear(
  client: BoardClient,
  year: number,
): Promise<SeasonRow | null> {
  const rows = await unwrap<SeasonRow>(
    client
      .from("seasons")
      .select(
        "id, year, sleeper_league_id, phase, expected_rosters, waiver_budget, roster_positions, league_synced_at",
      )
      .eq("year", year),
    "seasons",
  );
  return rows[0] ?? null;
}

/**
 * The newest `seasons` row, whatever year it is.
 *
 * `nfl_state.season` rolls over to the next year the moment the NFL does, months before this
 * league has a `seasons` row for it. Scoped to that year alone the board finds no season, so
 * every query below it stays disabled and the page reads as empty all offseason. This is the
 * fallback: the last season the league actually played, which the header labels as final.
 */
export async function fetchLatestSeason(
  client: BoardClient,
): Promise<SeasonRow | null> {
  const rows = await unwrap<SeasonRow>(
    client
      .from("seasons")
      .select(
        "id, year, sleeper_league_id, phase, expected_rosters, waiver_budget, roster_positions, league_synced_at",
      )
      .order("year", { ascending: false })
      .limit(1),
    "seasons",
  );
  return rows[0] ?? null;
}

export function fetchTeams(
  client: BoardClient,
  seasonId: number,
): Promise<TeamRow[]> {
  return unwrap<TeamRow>(
    client
      .from("teams")
      .select("id, sleeper_roster_id, team_name, member_id")
      .eq("season_id", seasonId),
    "teams",
  );
}

export function fetchMembers(client: BoardClient): Promise<MemberRow[]> {
  // The two public label columns only. `display_name` is the bare Sleeper username and is
  // never selected; `private.member_aliases` is never read at all. `members` is the one
  // unfiltered select here — it has no season column, and the board reads it as a lookup
  // table for the owner label.
  return unwrap<MemberRow>(
    client.from("members").select("id, sleeper_display_name, nickname"),
    "members",
  );
}

export function fetchTeamSeasonState(
  client: BoardClient,
  seasonId: number,
): Promise<TeamSeasonStateRow[]> {
  return unwrap<TeamSeasonStateRow>(
    client
      .from("team_season_state")
      .select(
        // No wins/losses/ties: nothing on the board reads a record any more (card change 2),
        // and the typed `Database` no longer names them, so selecting them would not compile.
        "season_id, team_id, faab_budget, faab_used, faab_remaining, points_for, points_against, is_eliminated, eliminated_week, elimination_source, state_version, synced_at",
      )
      .eq("season_id", seasonId),
    "team_season_state",
  );
}

export function fetchTeamWeekProjections(
  client: BoardClient,
  seasonId: number,
  week: number,
): Promise<TeamWeekProjectionRow[]> {
  return unwrap<TeamWeekProjectionRow>(
    client
      .from("team_week_projections")
      .select(
        "season_id, team_id, week, projected_points, starter_slots, filled_slots, empty_slots, starters_projected, missing_projections, coverage_pct, is_provisional, computed_at",
      )
      .eq("season_id", seasonId)
      .eq("week", week),
    "team_week_projections",
  );
}

export function fetchRosterHoldings(
  client: BoardClient,
  seasonId: number,
): Promise<RosterHoldingRow[]> {
  return unwrap<RosterHoldingRow>(
    client
      .from("roster_holdings")
      .select("team_id, sleeper_player_id, slot, slot_index, lineup_position")
      .eq("season_id", seasonId),
    "roster_holdings",
  );
}

export function fetchWeeklyResults(
  client: BoardClient,
  seasonId: number,
): Promise<WeeklyResultFetchRow[]> {
  return unwrap<WeeklyResultFetchRow>(
    client
      .from("weekly_results")
      .select("week, team_id, points, is_final, state_version")
      .eq("season_id", seasonId),
    "weekly_results",
  );
}

/**
 * The frozen snapshots for every eliminated team. Written once at elimination and never
 * updated, so this is a small table — at most one row per team per season.
 */
export function fetchFinalRosters(
  client: BoardClient,
  seasonId: number,
): Promise<FinalRosterRow[]> {
  return unwrap<FinalRosterRow>(
    client
      .from("final_rosters")
      .select("team_id, eliminated_week, holdings, frozen_at")
      .eq("season_id", seasonId),
    "final_rosters",
  );
}

/**
 * The directory for every player the board can show — roughly 360 live ids plus whatever the
 * frozen snapshots still name. One request per `IN_CHUNK_SIZE` ids, issued in parallel and
 * merged in id order; never one request per team.
 */
export async function fetchPlayers(
  client: BoardClient,
  sleeperPlayerIds: string[],
): Promise<PlayerRow[]> {
  if (sleeperPlayerIds.length === 0) {
    return [];
  }
  const batches = await Promise.all(
    chunkIds(sleeperPlayerIds).map((ids) =>
      unwrap<PlayerRow>(
        client
          .from("players")
          .select("sleeper_player_id, full_name, position, team")
          .in("sleeper_player_id", ids),
        "players",
      ),
    ),
  );
  // Promise.all resolves in argument order, so flattening keeps the caller's id order rather
  // than whichever batch came back first.
  return batches.flat();
}

/**
 * player_projections is keyed by the plain season year, not season_id, and is deliberately
 * not in the realtime publication — a run touches thousands of rows.
 */
export async function fetchPlayerProjections(
  client: BoardClient,
  season: number,
  week: number,
  sleeperPlayerIds: string[],
): Promise<PlayerProjectionRow[]> {
  if (sleeperPlayerIds.length === 0) {
    return [];
  }
  const batches = await Promise.all(
    chunkIds(sleeperPlayerIds).map((ids) =>
      unwrap<PlayerProjectionRow>(
        client
          .from("player_projections")
          .select("sleeper_player_id, league_points")
          .eq("season", season)
          .eq("week", week)
          .in("sleeper_player_id", ids),
        "player_projections",
      ),
    ),
  );
  return batches.flat();
}
