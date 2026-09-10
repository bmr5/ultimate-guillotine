import { describe, expect, it } from "vitest";

import { deriveSeason } from "./derive";
import { eventRecord, weekRecord } from "./fixtures.test-support";
import { ruleForWeek } from "./rules";
import type { ArchiveEvent } from "./types";

describe("2026 season archive", () => {
  it("records two Week 1 qualifications, no cuts, and 18 teams still alive", () => {
    const result = deriveSeason({
      weeks: [weekRecord()],
      events: [eventRecord(1), eventRecord(2)],
    });
    expect(result).toMatchObject({
      cuts: 0,
      qualifications: 2,
      remaining: 18,
      throughWeek: 1,
    });
  });
  it("does not count actual entry and survival as extra qualifications or cuts", () => {
    const result = deriveSeason({
      weeks: [weekRecord()],
      events: [
        eventRecord(1),
        eventRecord(2),
        eventRecord(3, {
          event_type: "gulag_entered",
          team_label: "Max",
          qualifier_label: "Ben",
          beneficiary_label: "Ben",
        }),
        eventRecord(4, { event_type: "gulag_survived" }),
      ],
    });
    expect(result).toMatchObject({ cuts: 0, qualifications: 2 });
  });
  it("does not turn no data, provisional results, or a missing entrant into official totals", () => {
    expect(deriveSeason({ weeks: [], events: [] }).remaining).toBeNull();
    for (const archive of [
      {
        weeks: [weekRecord(1, { status: "provisional" })],
        events: [eventRecord(1), eventRecord(2)],
      },
      { weeks: [weekRecord()], events: [eventRecord(1)] },
    ])
      expect(deriveSeason(archive)).toMatchObject({
        confirmedWeeks: 0,
        remaining: null,
      });
  });
  it("takes corrections and retractions before counting; never resurrects an old event", () => {
    const old = weekRecord();
    const corrected = weekRecord(1, { id: 101, revision: 2 });
    const events = [
      eventRecord(1),
      eventRecord(2),
      eventRecord(3, { week_revision_id: 101 }),
      eventRecord(4, { week_revision_id: 101 }),
    ];
    expect(
      deriveSeason({ weeks: [corrected, old], events }).weeks[0].events.map(
        (e) => e.id,
      ),
    ).toEqual([3, 4]);
    expect(
      deriveSeason({
        weeks: [old, { ...corrected, status: "retracted" }],
        events,
      }),
    ).toMatchObject({ qualifications: 0, remaining: null });
  });
  it("keeps a gap visible instead of claiming a current survivor total", () => {
    const result = deriveSeason({
      weeks: [weekRecord(13)],
      events: [
        eventRecord(1, {
          week_revision_id: 13,
          event_type: "eliminated",
          elimination_reason: "direct_cut",
        }),
      ],
    });
    expect(result).toMatchObject({
      cuts: 1,
      confirmedWeeks: 1,
      remaining: null,
      throughWeek: 0,
    });
  });
  it("matches the complete 18-team schedule with 17 terminal cuts and one champion", () => {
    let nextId = 0;
    const events: ArchiveEvent[] = [];
    const weeks = Array.from({ length: 17 }, (_, i) => weekRecord(i + 1));
    for (const week of weeks) {
      const rule = ruleForWeek(week.week);
      for (let j = 0; j < rule.cuts; j++)
        events.push(
          eventRecord(++nextId, {
            week_revision_id: week.id,
            event_type: "eliminated",
            elimination_reason:
              week.week === 17
                ? "championship_loss"
                : week.week >= 13
                  ? "direct_cut"
                  : "gulag_loss",
          }),
        );
      for (let j = 0; j < rule.entrants; j++)
        events.push(eventRecord(++nextId, { week_revision_id: week.id }));
      if (week.week === 17)
        events.push(
          eventRecord(++nextId, {
            week_revision_id: week.id,
            event_type: "champion",
          }),
        );
    }
    expect(deriveSeason({ weeks, events })).toMatchObject({
      cuts: 17,
      qualifications: 22,
      remaining: 1,
      throughWeek: 17,
    });
    expect(ruleForWeek(12)).toMatchObject({
      cuts: 2,
      entrants: 0,
      remaining: 6,
    });
  });
});
