import { useQuery } from "@tanstack/react-query";

import { postgrest } from "@/supabaseClient";

import {
  fetchEventPlayers,
  fetchSeasonArchive,
  type ArchiveClient,
} from "./fetchers";

const client = postgrest as unknown as ArchiveClient;
export function useSeasonArchive() {
  return useQuery({
    queryKey: ["history", "season-archive", 2026],
    queryFn: () => fetchSeasonArchive(client),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
}

export function useEventPlayers(snapshotId: number, enabled: boolean) {
  return useQuery({
    queryKey: ["history", "snapshot-players", snapshotId],
    queryFn: () => fetchEventPlayers(client, snapshotId),
    enabled,
    staleTime: 60_000,
  });
}
