import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SeasonResult } from "../types";
import { SeasonCard } from "./SeasonCard";

const SEASON: SeasonResult = {
  season: 2024,
  championLabel: "Alpha",
  championMemberId: 1,
  coChampionLabel: null,
  coChampionMemberId: null,
  runnerUpLabel: null,
  runnerUpMemberId: null,
  thirdLabel: null,
  thirdMemberId: null,
  teamCount: 19,
  eliminations: [
    // 2024's grid states both counts; the `0` is a figure the sheet wrote, not a missing one.
    { week: 2, order: 1, memberId: null, gulagOut: 2, poolOut: 0 },
    { week: 3, order: 2, memberId: 7, gulagOut: null, poolOut: null },
  ],
  notes: "co-champions, tied on points",
  loadedAt: "2026-09-09T12:00:00Z",
};

describe("SeasonCard", () => {
  it("leads with the champion", () => {
    render(<SeasonCard season={SEASON} />);
    expect(screen.getByText("Champion 2024")).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText(/19 teams/)).toBeInTheDocument();
    expect(
      screen.getByText("co-champions, tied on points"),
    ).toBeInTheDocument();
  });

  // Ben's ruling: no eliminations section on the card, even when the season has the rows.
  it("carries no eliminations section", () => {
    render(<SeasonCard season={SEASON} />);
    expect(
      screen.queryByRole("button", { name: /eliminations/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Week 2/)).not.toBeInTheDocument();
    expect(screen.queryByText(/eliminated/)).not.toBeInTheDocument();
  });

  // Ben's ruling: a champion the directory cannot name is a manager who has left, which is
  // what "Former manager" says. "Unlisted" read as a hole in the data.
  it("calls a champion it could not resolve a former manager", () => {
    render(
      <SeasonCard
        season={{ ...SEASON, championLabel: null, championMemberId: 42 }}
      />,
    );
    expect(screen.getByText("Former manager")).toBeInTheDocument();
    expect(screen.queryByText("Unlisted")).not.toBeInTheDocument();
  });

  // The other half of the same null label: no champion on file at all. Calling that a
  // former manager would claim a person the sheet never named.
  it("says a season with no champion recorded is not recorded", () => {
    render(
      <SeasonCard
        season={{ ...SEASON, championLabel: null, championMemberId: null }}
      />,
    );
    expect(screen.getByText("Not recorded")).toBeInTheDocument();
    expect(screen.queryByText("Former manager")).not.toBeInTheDocument();
  });

  it("keeps a runner-up it could not name, and drops one never recorded", () => {
    render(
      <SeasonCard
        season={{
          ...SEASON,
          runnerUpLabel: null,
          runnerUpMemberId: 42,
          thirdLabel: "Charlie",
          thirdMemberId: 3,
        }}
      />,
    );
    // The row recorded a runner-up, so the clause survives with the same word the champion
    // line uses; the co-champion the row left null says nothing at all.
    expect(
      screen.getByText(/Runner-up Former manager · Third Charlie · 19 teams/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Co-champion/)).not.toBeInTheDocument();
  });
});
