import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SeasonResult } from "../types";
import { SeasonCard } from "./SeasonCard";

const SEASON: SeasonResult = {
  season: 2024,
  championLabel: "Alpha",
  coChampionLabel: null,
  runnerUpLabel: null,
  thirdLabel: null,
  teamCount: 19,
  eliminations: [
    {
      week: 2,
      order: 1,
      memberId: null,
      gulagOut: 2,
      poolOut: 0,
      remaining: 17,
    },
    {
      week: 3,
      order: 2,
      memberId: 7,
      gulagOut: null,
      poolOut: null,
      remaining: null,
    },
  ],
  notes: "co-champions, tied on points",
  loadedAt: "2026-09-09T12:00:00Z",
};

describe("SeasonCard", () => {
  it("leads with the champion", () => {
    render(<SeasonCard season={SEASON} labelForMember={() => "Bravo"} />);
    expect(screen.getByText("Champion 2024")).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText(/19 teams/)).toBeInTheDocument();
    expect(
      screen.getByText("co-champions, tied on points"),
    ).toBeInTheDocument();
  });

  it("expands to counts, and to names where the data has them", () => {
    render(<SeasonCard season={SEASON} labelForMember={() => "Bravo"} />);
    const toggle = screen.getByRole("button", { name: /eliminations/i });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByText(/2 out of the gulag, 0 from the pool, 17 remaining/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Bravo/)).toBeInTheDocument();
  });

  it("says when a champion could not be resolved", () => {
    render(
      <SeasonCard
        season={{ ...SEASON, championLabel: null }}
        labelForMember={() => "Bravo"}
      />,
    );
    expect(screen.getByText("Unlisted")).toBeInTheDocument();
  });

  // Ben's ruling: a figure the sheet never recorded says so in words. Never a `0` — that is a
  // week where nobody went out, which is a different fact — and never a bare dash.
  it("says a missing count is not recorded rather than showing a zero", () => {
    render(
      <SeasonCard
        season={{
          ...SEASON,
          eliminations: [
            {
              week: 5,
              order: 1,
              memberId: null,
              gulagOut: null,
              poolOut: 3,
              remaining: null,
            },
          ],
        }}
        labelForMember={() => null}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /eliminations/i }));
    const line = screen.getByText(/Week 5/);
    expect(line).toHaveTextContent(
      "gulag not recorded, 3 from the pool, remaining not recorded",
    );
    expect(line.textContent).not.toContain("0");
    expect(line.textContent).not.toContain("—");
  });
});
