import { ruleForWeek } from "./rules";
import type { ArchiveEvent, ArchiveWeek } from "./types";

export function weekRecord(
  week = 1,
  patch: Partial<ArchiveWeek> = {},
): ArchiveWeek {
  return {
    id: week,
    season: 2026,
    week,
    revision: 1,
    is_correction: false,
    status: "confirmed",
    remaining_teams: ruleForWeek(week).remaining,
    checked_at: "2026-09-15T13:00:00Z",
    rules_version: "2026-v1",
    ...patch,
  };
}
export function eventRecord(
  id: number,
  patch: Partial<ArchiveEvent> = {},
): ArchiveEvent {
  return {
    id,
    week_revision_id: 1,
    event_key: `event-${id}`,
    event_type: "gulag_qualified",
    team_id: id,
    team_label: `Team ${id}`,
    manager_label: null,
    qualification_week: 1,
    contest_week: 2,
    contest_id: "2026-w2",
    qualifier_label: null,
    beneficiary_label: null,
    elimination_reason: null,
    score: 100,
    opponent_label: null,
    opponent_score: null,
    faab_remaining: null,
    money_as_of: null,
    effective_at: "2026-09-15T03:30:00Z",
    roster_coverage: "missing",
    money_coverage: "missing",
    ...patch,
  };
}
