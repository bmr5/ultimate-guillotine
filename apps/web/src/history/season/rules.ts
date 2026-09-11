/** Display schedule only. Official outcomes always come from the adjudicator's archive. */
export function ruleForWeek(week: number) {
  if (!Number.isInteger(week) || week < 1 || week > 17)
    throw new Error("Invalid 2026 week");
  if (week === 1)
    return {
      cuts: 0,
      entrants: 2,
      remaining: 18,
      phase: "Gulag qualification",
      description: "Two teams qualify for the Week 2 gulag. Nobody is cut.",
    };
  if (week <= 11)
    return {
      cuts: 1,
      entrants: 2,
      remaining: 19 - week,
      phase: "Gulag",
      description: `The gulag loser is cut. Two eligible pool teams qualify for Week ${week + 1}.`,
    };
  if (week === 12)
    return {
      cuts: 2,
      entrants: 0,
      remaining: 6,
      phase: "Double cut",
      description:
        "The last gulag loser and the lowest eligible general-pool scorer are cut. No new gulag.",
    };
  if (week <= 16)
    return {
      cuts: 1,
      entrants: 0,
      remaining: 18 - week,
      phase: "Direct cut",
      description: "The lowest-scoring remaining team is cut. No gulag.",
    };
  return {
    cuts: 1,
    entrants: 0,
    remaining: 1,
    phase: "Championship",
    description:
      "The final two play for the title. One champion, one runner-up.",
  };
}
