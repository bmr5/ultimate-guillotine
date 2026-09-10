import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { boardClient } from "@/board/boardClient";

import { isRecord } from "./derive/json";
import { ownerLabelFor } from "./derive/ownerLabel";
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
 *
 * The array's own elements are narrowed through `isRecord` first, the check every reader of a
 * `jsonb` array here shares: the column's constraint does not forbid a `null` or a bare string
 * inside the array, and reading `.week` off one throws — which would cost the whole page rather
 * than the one malformed week. A dropped element takes its `order` with it, so the numbering
 * the card keys on comes from the document, never from the surviving elements' positions.
 */
function toEliminations(value: unknown): SeasonElimination[] {
  if (!Array.isArray(value)) return [];
  return (value as unknown[]).flatMap((entry, index) =>
    !isRecord(entry)
      ? []
      : [
          {
            week: typeof entry.week === "number" ? entry.week : 0,
            order: Number(entry.order ?? index + 1),
            memberId:
              typeof entry.member_id === "number" ? entry.member_id : null,
            gulagOut:
              typeof entry.gulag_out === "number" ? entry.gulag_out : null,
            poolOut: typeof entry.pool_out === "number" ? entry.pool_out : null,
          },
        ],
  );
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
   * Wrapped rather than called inline so the identity is stable across renders: it is a
   * dependency of the `seasons` memo below, and a fresh closure each render would rebuild
   * every season object on every render.
   */
  const labelForMember = useCallback(
    (memberId: number | null): string | null =>
      ownerLabelFor(memberId, members.data ?? []),
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
