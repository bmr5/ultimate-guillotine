import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { boardClient } from "@/board/boardClient";
import { resolveOwnerLabel } from "@/board/derive/join";

import { fetchHistoryMembers, fetchSeasonResults } from "./fetchers";
import { historyKeys } from "./queryKeys";
import type { SeasonElimination, SeasonResult } from "./types";
import { HISTORY_STALE_MS } from "./useTradeCatalog";

/** A failed query, named by the part of the page it was loading — `useTradeCatalog`'s shape. */
export interface SeasonResultsError {
  source: string;
  error: Error;
}

/**
 * `season_results.eliminations` is a JSON document the loader wrote, not a typed column, so it
 * is read defensively: an entry that is missing a figure keeps it as `null` rather than
 * defaulting to `0`. The two are different facts — "nobody went out that week" and "the sheet
 * never recorded it" — and `SeasonCard` says which one it is looking at.
 */
function toEliminations(value: unknown): SeasonElimination[] {
  if (!Array.isArray(value)) return [];
  return (value as Record<string, unknown>[]).map((entry, index) => ({
    week: Number(entry.week ?? 0),
    order: Number(entry.order ?? index + 1),
    memberId: typeof entry.member_id === "number" ? entry.member_id : null,
    gulagOut: typeof entry.gulag_out === "number" ? entry.gulag_out : null,
    poolOut: typeof entry.pool_out === "number" ? entry.pool_out : null,
    remaining: typeof entry.remaining === "number" ? entry.remaining : null,
    note: typeof entry.note === "string" ? entry.note : null,
  }));
}

export function useSeasonResults() {
  const results = useQuery({
    queryKey: historyKeys.seasonResults(),
    queryFn: () => fetchSeasonResults(boardClient),
    staleTime: HISTORY_STALE_MS,
  });
  const members = useQuery({
    queryKey: historyKeys.members(),
    queryFn: () => fetchHistoryMembers(boardClient),
    staleTime: HISTORY_STALE_MS,
  });

  /**
   * `null`, not a placeholder string, when the id is absent or names nobody in `members`: the
   * card decides how an unresolved owner reads, and only the card knows whether it is writing
   * a champion line or an elimination line.
   *
   * The label itself is `resolveOwnerLabel`'s — nickname first, then the Sleeper display name.
   * `members.display_name` is a real name and never reaches a public page.
   */
  const labelForMember = useCallback(
    (memberId: number | null): string | null => {
      if (memberId === null) return null;
      const member = (members.data ?? []).find(
        (candidate) => candidate.id === memberId,
      );
      return member === undefined ? null : resolveOwnerLabel(member);
    },
    [members.data],
  );

  const seasons: SeasonResult[] = useMemo(
    () =>
      (results.data ?? []).map((row) => ({
        season: row.season,
        championLabel: labelForMember(row.champion_member_id),
        coChampionLabel: labelForMember(row.co_champion_member_id),
        runnerUpLabel: labelForMember(row.runner_up_member_id),
        thirdLabel: labelForMember(row.third_member_id),
        teamCount: row.team_count,
        eliminations: toEliminations(row.eliminations),
        notes: row.notes,
        loadedAt: row.loaded_at,
      })),
    [results.data, labelForMember],
  );

  const loadedAt = useMemo(() => {
    const stamps = seasons
      .map((season) => Date.parse(season.loadedAt))
      .filter((stamp) => Number.isFinite(stamp));
    return stamps.length === 0 ? null : Math.max(...stamps);
  }, [seasons]);

  // Named by source and shaped like `useTradeCatalog`'s, so both pages render a failure the
  // same way: "Could not load the season results" rather than a bare PostgREST message.
  const errors = useMemo(
    () =>
      (
        [
          { source: "Season results", error: results.error },
          { source: "Members", error: members.error },
        ] satisfies { source: string; error: Error | null }[]
      ).filter(
        (entry): entry is SeasonResultsError => entry.error instanceof Error,
      ),
    [results.error, members.error],
  );

  return {
    seasons,
    loadedAt,
    labelForMember,
    isPending: results.isPending || members.isPending,
    errors,
  };
}
