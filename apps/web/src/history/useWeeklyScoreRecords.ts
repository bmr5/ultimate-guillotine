import type { PostgrestClient } from "@supabase/postgrest-js";
import { useQuery } from "@tanstack/react-query";

import { postgrest } from "@/supabaseClient";

export type WeeklyScoreRecord = {
  key: string;
  rank: number;
  season: number;
  week: number;
  team_label: string;
  manager_label: string | null;
  points: number;
};
export type WeeklyScoreRecords = {
  highs: WeeklyScoreRecord[];
  lows: WeeklyScoreRecord[];
  full_lineup_lows: WeeklyScoreRecord[];
  coverage: { season: number; weeks: number; scores: number }[];
};
type RecordsDatabase = {
  public: {
    Tables: Record<string, never>;
    Views: Record<string, never>;
    Functions: {
      get_weekly_score_records: {
        Args: Record<string, never>;
        Returns: WeeklyScoreRecords;
      };
    };
  };
};
export async function fetchWeeklyScoreRecords(
  client: PostgrestClient<RecordsDatabase>,
) {
  const result = await client.rpc("get_weekly_score_records");
  if (result.error || !result.data)
    throw new Error("Weekly score records are unavailable.");
  return result.data;
}
export function useWeeklyScoreRecords() {
  return useQuery({
    queryKey: ["history", "weekly-score-records"],
    queryFn: () =>
      fetchWeeklyScoreRecords(
        postgrest as unknown as PostgrestClient<RecordsDatabase>,
      ),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
}
