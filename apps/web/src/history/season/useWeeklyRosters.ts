import { useQuery } from "@tanstack/react-query";

import { postgrest } from "@/supabaseClient";

import { fetchWeeklyRosters, type ArchiveClient } from "./fetchers";

export function useWeeklyRosters(revisionId: number | undefined) {
  return useQuery({
    queryKey: ["history", "weekly-rosters", revisionId],
    queryFn: () =>
      fetchWeeklyRosters(postgrest as unknown as ArchiveClient, revisionId!),
    enabled: revisionId !== undefined,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
}
