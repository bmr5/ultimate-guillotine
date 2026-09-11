export type WeekStatus =
  "provisional" | "confirmed" | "unresolved" | "retracted";
export type EventKind =
  | "gulag_qualified"
  | "gulag_entered"
  | "gulag_survived"
  | "eliminated"
  | "champion";
export type Coverage = "complete" | "partial" | "missing";

export type ArchiveWeek = {
  id: number;
  season: number;
  week: number;
  revision: number;
  is_correction: boolean;
  status: WeekStatus;
  remaining_teams: number | null;
  checked_at: string;
  rules_version: string;
};

export type ArchiveEvent = {
  id: number;
  week_revision_id: number;
  event_key: string;
  event_type: EventKind;
  team_id: number;
  team_label: string;
  manager_label: string | null;
  qualification_week: number | null;
  contest_week: number | null;
  contest_id: string | null;
  qualifier_label: string | null;
  beneficiary_label: string | null;
  elimination_reason: "gulag_loss" | "direct_cut" | "championship_loss" | null;
  score: number | null;
  opponent_label: string | null;
  opponent_score: number | null;
  faab_remaining: number | null;
  money_as_of: string | null;
  effective_at: string | null;
  roster_coverage: Coverage;
  money_coverage: Coverage;
};

export type ArchivePlayer = {
  snapshot_id: number;
  player_id: string;
  player_label: string;
  position: string | null;
  slot: string | null;
  started: boolean;
  owned_at_cutoff: boolean;
  keeper: boolean | null;
  points: number | null;
};

export type SeasonArchive = { weeks: ArchiveWeek[]; events: ArchiveEvent[] };

type ReadTable<T> = { Row: T; Insert: never; Update: never; Relationships: [] };
export type ArchiveDatabase = {
  public: {
    Tables: {
      season_history_current_weeks: ReadTable<ArchiveWeek>;
      season_history_current_events: ReadTable<ArchiveEvent>;
      season_history_current_players: ReadTable<ArchivePlayer>;
    };
    Views: Record<string, never>;
    Functions: Record<string, never>;
  };
};
