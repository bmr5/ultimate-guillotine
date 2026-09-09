export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[];

/** The board holds anon `select` only, so Insert/Update exist purely to satisfy supabase-js. */
type ReadOnlyTable<Row extends Record<string, unknown>> = {
  Row: Row;
  Insert: Row;
  Update: Partial<Row>;
  Relationships: [];
};

export type RosterSlot = "starter" | "bench" | "ir" | "taxi";
export type EliminationSource = "adjudicator" | "sleeper_inferred" | "manual";

/**
 * One entry in `public.final_rosters.holdings`. Deliberately identical to the
 * `roster_holdings` columns the board reads, so one builder serves live and frozen rosters.
 */
export interface FinalRosterHolding {
  sleeper_player_id: string;
  slot: RosterSlot;
  slot_index: number | null;
  lineup_position: string | null;
}

/**
 * Only the columns the board selects, so a drifted column name fails `tsc` rather than
 * silently reading `undefined`. Every postgres `numeric` column below is typed `number`:
 * PostgREST serialises rows with `to_json`, and `to_json(numeric)` emits an unquoted JSON
 * literal, so these arrive as JS numbers, never as strings. `bigint` identity keys arrive
 * as numbers for the same reason; the league's ids stay far inside `Number.MAX_SAFE_INTEGER`.
 * `timestamptz` and `date` arrive as ISO strings.
 */
export interface Database {
  public: {
    Tables: {
      seasons: ReadOnlyTable<{
        id: number;
        year: number;
        sleeper_league_id: string;
        phase: string;
        expected_rosters: number;
        waiver_budget: number | null;
        roster_positions: Json;
        league_synced_at: string | null;
      }>;
      members: ReadOnlyTable<{
        id: number;
        /**
         * The bare Sleeper username. Typed because the column exists; never selected and
         * never rendered — owner labels use nickname, then sleeper_display_name.
         */
        display_name: string;
        /** Written by `ug sleeper sync` from Sleeper's user record. */
        sleeper_display_name: string | null;
        /** Written by `ug members aliases load` as the first alias; null when none. */
        nickname: string | null;
      }>;
      teams: ReadOnlyTable<{
        id: number;
        season_id: number;
        member_id: number;
        sleeper_user_id: string;
        sleeper_roster_id: number;
        team_name: string;
      }>;
      weekly_results: ReadOnlyTable<{
        id: number;
        season_id: number;
        week: number;
        team_id: number;
        points: number;
        state_version: number;
        is_final: boolean;
      }>;
      players: ReadOnlyTable<{
        id: number;
        sleeper_player_id: string;
        full_name: string;
        position: string | null;
        team: string | null;
        active: boolean;
        synced_at: string;
      }>;
      roster_holdings: ReadOnlyTable<{
        season_id: number;
        team_id: number;
        sleeper_player_id: string;
        slot: RosterSlot;
        slot_index: number | null;
        lineup_position: string | null;
        synced_at: string;
      }>;
      /**
       * The elimination snapshot from Spec issue 10. `holdings` is the frozen roster; Sleeper
       * roster churn after elimination never touches it.
       */
      final_rosters: ReadOnlyTable<{
        season_id: number;
        team_id: number;
        /**
         * Nullable in the shipped migration (Spec issue 11): a provisional Sleeper-inferred
         * elimination may not know the week yet, but the snapshot is still taken.
         */
        eliminated_week: number | null;
        holdings: FinalRosterHolding[];
        frozen_at: string;
      }>;
      team_season_state: ReadOnlyTable<{
        season_id: number;
        team_id: number;
        faab_budget: number;
        faab_used: number;
        /** A stored generated column (`faab_budget - faab_used`); read-only in every sense. */
        faab_remaining: number;
        /**
         * The season total the board shows. `wins`, `losses` and `ties` exist on the table but
         * are neither typed nor selected here: Ben's card change 2 removed every record concept
         * from the board, and a column no view reads is a column the board should not fetch.
         */
        points_for: number;
        points_against: number;
        is_eliminated: boolean;
        eliminated_week: number | null;
        elimination_source: EliminationSource | null;
        state_version: number;
        synced_at: string;
      }>;
      team_week_projections: ReadOnlyTable<{
        season_id: number;
        team_id: number;
        week: number;
        projected_points: number;
        starter_slots: number;
        filled_slots: number;
        empty_slots: number;
        starters_projected: number;
        missing_projections: number;
        coverage_pct: number;
        is_provisional: boolean;
        computed_at: string;
      }>;
      /** Keyed by the plain NFL season year, not `seasons.id`: a projection is not league-scoped. */
      player_projections: ReadOnlyTable<{
        season: number;
        week: number;
        sleeper_player_id: string;
        league_points: number | null;
        pts_ppr: number | null;
        source: string;
        coverage_flagged: boolean;
        run_coverage_pct: number | null;
        projected_at: string;
        synced_at: string;
      }>;
      nfl_state: ReadOnlyTable<{
        id: number;
        season: number;
        season_type: string;
        week: number;
        display_week: number | null;
        synced_at: string;
      }>;
    };
    Views: { [_ in never]: never };
    Functions: { [_ in never]: never };
    Enums: { [_ in never]: never };
    CompositeTypes: { [_ in never]: never };
  };
}

export type TableRow<T extends keyof Database["public"]["Tables"]> =
  Database["public"]["Tables"][T]["Row"];

export interface RosterPlayer {
  sleeperPlayerId: string;
  fullName: string;
  position: string | null;
  nflTeam: string | null;
  slot: RosterSlot;
  slotIndex: number | null;
  lineupPosition: string | null;
  /** null means "no projection", never zero. */
  projectedPoints: number | null;
}

export interface BoardTeam {
  teamId: number;
  teamName: string;
  ownerName: string;
  sleeperRosterId: number;
  projectedPoints: number | null;
  coveragePct: number | null;
  isProvisional: boolean;
  projectionComputedAt: string | null;
  faabRemaining: number | null;
  /**
   * The season's total points — `team_season_state.points_for`, or the fold of
   * `weekly_results` when the team has no state row. The card calls it `Total`; there is no
   * win-loss record on the board at all (Ben's card change 2).
   */
  pointsFor: number;
  /**
   * `team_week_projections.starters_projected` and `.starter_slots` for the week: how many of
   * the lineup's slots Sleeper actually has a projection for, out of how many there are. They
   * exist so the partial badge can say *why* it is there rather than only that it is. null when
   * the week has no projection row, in which case there is no partial state to explain either.
   */
  startersProjected: number | null;
  starterSlots: number | null;
  isEliminated: boolean;
  eliminatedWeek: number | null;
  eliminationSource: EliminationSource | null;
  /**
   * `team_week_projections.empty_slots` for the week: how many lineup slots the data layer
   * found nobody in when it computed the projection. null when there is no projection row for
   * the week, in which case the board counts the empty slots off the roster itself.
   */
  emptySlots: number | null;
  /** True when `roster` came from the frozen `final_rosters` snapshot, not live holdings. */
  isRosterFrozen: boolean;
  roster: RosterPlayer[];
}

/**
 * `points_for` is the URL value the season-total sort has always been shared under, and it stays
 * that way: the label changed to `Total` (Ben's card change 1), but a link someone already sent
 * to the league carries the old spelling and must keep resolving to the same sort.
 */
export const SORT_MODES = ["projection", "faab", "points_for"] as const;
export type SortMode = (typeof SORT_MODES)[number];
export const DEFAULT_SORT_MODE: SortMode = "projection";

export const SORT_MODE_LABELS: Record<SortMode, string> = {
  projection: "Projection",
  faab: "FAAB",
  points_for: "Total",
};

export function parseSortMode(raw: string | null | undefined): SortMode {
  return SORT_MODES.includes(raw as SortMode)
    ? (raw as SortMode)
    : DEFAULT_SORT_MODE;
}

/**
 * The positions the quick view can be narrowed to, in lineup order. These are Sleeper's own
 * position codes, which is what `players.position` carries, so a filter compares to a roster
 * row without a translation table in between.
 */
export const POSITION_FILTERS = ["QB", "RB", "WR", "TE", "K", "DEF"] as const;
export type PositionFilter = (typeof POSITION_FILTERS)[number];

/** The segmented control's value for "no position filter"; `?pos` is absent in that state. */
export const ALL_POSITIONS_VALUE = "all";

/** The label the "no filter" segment carries. */
export const ALL_POSITIONS_LABEL = "All";

/**
 * `?pos=TE`, or null for the whole board. Case-insensitive because the parameter is shared by
 * hand as often as it is clicked, and `?pos=te` means the same thing to a reader.
 */
export function parsePositionFilter(
  raw: string | null | undefined,
): PositionFilter | null {
  const value = (raw ?? "").trim().toUpperCase();
  return POSITION_FILTERS.includes(value as PositionFilter)
    ? (value as PositionFilter)
    : null;
}

/**
 * The two sorts a position view offers. The season total is not among them: the question the
 * view answers is who can bid and who needs the position, and a total answers neither.
 */
export const POSITION_SORT_MODES = ["faab", "projection"] as const;

/** FAAB leads, because the view exists to find who can outbid whom. */
export const DEFAULT_POSITION_SORT_MODE: SortMode = "faab";

/** The sort a position view is in, defaulting to FAAB rather than the board's own default. */
export function parsePositionSortMode(
  raw: string | null | undefined,
): SortMode {
  return POSITION_SORT_MODES.includes(
    raw as (typeof POSITION_SORT_MODES)[number],
  )
    ? (raw as SortMode)
    : DEFAULT_POSITION_SORT_MODE;
}
