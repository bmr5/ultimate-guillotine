import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SeasonResult } from "../types";
import { WinnersStrip } from "./WinnersStrip";

function season(overrides: Partial<SeasonResult>): SeasonResult {
  return {
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
    eliminations: [],
    notes: null,
    loadedAt: "2026-09-09T12:00:00Z",
    ...overrides,
  };
}

describe("WinnersStrip", () => {
  it("lists a season against its champion", () => {
    render(<WinnersStrip seasons={[season({})]} />);
    expect(screen.getByRole("list", { name: /winners/i })).toBeInTheDocument();
    expect(screen.getByText("2024")).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
  });

  // The strip and the season card read the same season, so they have to reach the same two
  // answers from the same null label — the id is what tells them apart.
  it("names a champion it could not resolve a former manager", () => {
    render(
      <WinnersStrip
        seasons={[season({ championLabel: null, championMemberId: 42 })]}
      />,
    );
    expect(screen.getByText("Former manager")).toBeInTheDocument();
    expect(screen.queryByText("Not recorded")).not.toBeInTheDocument();
  });

  it("says a season with no champion recorded is not recorded", () => {
    render(
      <WinnersStrip
        seasons={[season({ championLabel: null, championMemberId: null })]}
      />,
    );
    expect(screen.getByText("Not recorded")).toBeInTheDocument();
    expect(screen.queryByText("Former manager")).not.toBeInTheDocument();
  });
});
