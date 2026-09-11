import type { PostgrestClient } from "@supabase/postgrest-js";

import type {
  ArchiveDatabase,
  ArchiveEvent,
  ArchivePlayer,
  SeasonArchive,
} from "./types";

export type ArchiveClient = PostgrestClient<ArchiveDatabase>;
const EVENT_COLUMNS =
  "id, week_revision_id, event_key, event_type, team_id, team_label, manager_label, qualification_week, contest_week, contest_id, qualifier_label, beneficiary_label, elimination_reason, score, opponent_label, opponent_score, faab_remaining, money_as_of, effective_at, roster_coverage, money_coverage";

export async function fetchSeasonArchive(
  client: ArchiveClient,
): Promise<SeasonArchive> {
  const result = await client
    .from("season_history_current_weeks")
    .select(
      "id, season, week, revision, is_correction, status, remaining_teams, checked_at, rules_version",
    )
    .eq("season", 2026)
    .order("week");
  if (result.error)
    throw new Error("Season history is unavailable. Please try again shortly.");
  const weeks = result.data ?? [];
  if (!weeks.length) return { weeks: [], events: [] };
  const events: ArchiveEvent[] = [];
  // Page through the complete result, including future richer event histories.
  for (let offset = 0; ; offset += 500) {
    const page = await client
      .from("season_history_current_events")
      .select(EVENT_COLUMNS)
      .in(
        "week_revision_id",
        weeks.map((w) => w.id),
      )
      .order("id")
      .range(offset, offset + 499);
    if (page.error)
      throw new Error("Could not load the weekly events. Please try again.");
    events.push(...(page.data ?? []));
    if ((page.data?.length ?? 0) < 500) break;
  }
  return { weeks, events };
}

export async function fetchEventPlayers(
  client: ArchiveClient,
  snapshotId: number,
): Promise<ArchivePlayer[]> {
  const rows: ArchivePlayer[] = [];
  for (let offset = 0; ; offset += 100) {
    const page = await client
      .from("season_history_current_players")
      .select(
        "snapshot_id, player_id, player_label, position, slot, started, owned_at_cutoff, keeper, points",
      )
      .eq("snapshot_id", snapshotId)
      .order("player_id")
      .range(offset, offset + 99);
    if (page.error) throw new Error("Could not load the saved roster.");
    rows.push(...(page.data ?? []));
    if ((page.data?.length ?? 0) < 100) return rows;
  }
}
