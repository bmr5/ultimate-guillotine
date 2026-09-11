import { ruleForWeek } from "./rules";
import type { ArchiveEvent, ArchiveWeek, SeasonArchive } from "./types";

export const EVENT_LABELS = {
  gulag_qualified: "Qualified for gulag",
  gulag_entered: "Entered gulag",
  gulag_survived: "Survived gulag",
  eliminated: "Officially cut",
  champion: "Champion",
};

export function eventLabel(event: ArchiveEvent) {
  return event.elimination_reason === "championship_loss"
    ? "Championship runner-up"
    : EVENT_LABELS[event.event_type];
}

/** Do not show a complete week's totals if the published bundle is incomplete. */
export function weekIsComplete(week: ArchiveWeek, events: ArchiveEvent[]) {
  if (week.status !== "confirmed") return false;
  const rule = ruleForWeek(week.week);
  const cuts = events.filter((e) => e.event_type === "eliminated");
  const qualifiers = events.filter((e) => e.event_type === "gulag_qualified");
  return (
    cuts.length === rule.cuts &&
    new Set(cuts.map((e) => e.team_id)).size === rule.cuts &&
    qualifiers.length === rule.entrants &&
    new Set(qualifiers.map((e) => e.team_id)).size === rule.entrants &&
    week.remaining_teams === rule.remaining &&
    (week.week !== 17 ||
      events.filter((e) => e.event_type === "champion").length === 1)
  );
}

export function deriveSeason(archive: SeasonArchive) {
  // The view already picks the latest revision, but keep this boundary safe for cached inputs.
  const latest = new Map<number, ArchiveWeek>();
  for (const week of archive.weeks) {
    if (week.season !== 2026 || week.week < 1 || week.week > 17) continue;
    if ((latest.get(week.week)?.revision ?? -1) < week.revision)
      latest.set(week.week, week);
  }
  const weeks = Array.from({ length: 17 }, (_, i) => {
    const number = i + 1;
    const record = latest.get(number);
    const events =
      !record || record.status === "retracted"
        ? []
        : archive.events.filter((e) => e.week_revision_id === record.id);
    return {
      number,
      record,
      events,
      complete: record ? weekIsComplete(record, events) : false,
      rule: ruleForWeek(number),
    };
  });
  const confirmed = weeks.filter((w) => w.complete);
  const confirmedEvents = confirmed.flatMap((w) => w.events);
  let throughWeek = 0;
  for (const week of weeks) {
    if (!week.complete) break;
    throughWeek = week.number;
  }
  return {
    weeks,
    throughWeek,
    cuts: confirmedEvents.filter((e) => e.event_type === "eliminated").length,
    qualifications: confirmedEvents.filter(
      (e) => e.event_type === "gulag_qualified",
    ).length,
    confirmedWeeks: confirmed.length,
    // An empty or interrupted archive must not imply a current team count.
    remaining:
      throughWeek > 0 ? weeks[throughWeek - 1].record!.remaining_teams : null,
  };
}
