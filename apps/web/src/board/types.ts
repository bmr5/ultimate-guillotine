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
        wins: number;
        losses: number;
        ties: number;
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
  wins: number;
  losses: number;
  ties: number;
  pointsFor: number;
  isEliminated: boolean;
  eliminatedWeek: number | null;
  eliminationSource: EliminationSource | null;
  /** True when `roster` came from the frozen `final_rosters` snapshot, not live holdings. */
  isRosterFrozen: boolean;
  roster: RosterPlayer[];
}

export const SORT_MODES = ["projection", "faab", "points_for"] as const;
export type SortMode = (typeof SORT_MODES)[number];
export const DEFAULT_SORT_MODE: SortMode = "projection";

export const SORT_MODE_LABELS: Record<SortMode, string> = {
  projection: "Projection",
  faab: "FAAB",
  points_for: "Points for",
};

export function parseSortMode(raw: string | null | undefined): SortMode {
  return SORT_MODES.includes(raw as SortMode)
    ? (raw as SortMode)
    : DEFAULT_SORT_MODE;
}
