import type { PostgrestClient } from "@supabase/postgrest-js";
import { useQuery } from "@tanstack/react-query";

import { postgrest } from "@/supabaseClient";

import type { WeeklyScoreRecord } from "./useWeeklyScoreRecords";

export type ScoringPlayer = {
  player_id: string | null;
  player_label: string;
  position: string | null;
  slot: string;
  points: number | null;
};
export type ScoreRecordRoster = Omit<WeeklyScoreRecord, "rank"> & {
  roster_at: string | null;
  roster: { starters: ScoringPlayer[]; bench: ScoringPlayer[] } | null;
};
export type RosterDatabase = {
  public: {
    Tables: Record<string, never>;
    Views: Record<string, never>;
    Functions: {
      get_score_record_roster: {
        Args: { p_record_key: string };
        Returns: ScoreRecordRoster | null;
      };
    };
  };
};
export async function fetchScoreRecordRoster(
  client: PostgrestClient<RosterDatabase>,
  key: string,
) {
  const result = await client.rpc("get_score_record_roster", {
    p_record_key: key,
  });
  if (result.error) throw new Error("Could not load this week's roster.");
  return result.data;
}
export function useScoreRecordRoster(key: string) {
  return useQuery({
    queryKey: ["history", "score-record-roster", key],
    queryFn: () =>
      fetchScoreRecordRoster(
        postgrest as unknown as PostgrestClient<RosterDatabase>,
        key,
      ),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
}
