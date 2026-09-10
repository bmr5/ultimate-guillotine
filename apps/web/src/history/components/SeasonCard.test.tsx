import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SeasonElimination, SeasonResult } from "../types";
import { SeasonCard } from "./SeasonCard";

const SEASON: SeasonResult = {
  season: 2024,
  championLabel: "Alpha",
  coChampionLabel: null,
  runnerUpLabel: null,
  thirdLabel: null,
  teamCount: 19,
  eliminations: [
    // 2024's grid states both counts; the `0` is a figure the sheet wrote, not a missing one.
    { week: 2, order: 1, memberId: null, gulagOut: 2, poolOut: 0 },
    { week: 3, order: 2, memberId: 7, gulagOut: null, poolOut: null },
  ],
  notes: "co-champions, tied on points",
  loadedAt: "2026-09-09T12:00:00Z",
};

/** The card with one elimination row on it, already expanded. Returns that row's element. */
function renderOneLine(entry: SeasonElimination): HTMLElement {
  render(
    <SeasonCard
      season={{ ...SEASON, eliminations: [entry] }}
      labelForMember={() => null}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /eliminations/i }));
  return screen.getByText(new RegExp(`Week ${entry.week}`));
}

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
      screen.getByText("Week 2 · 2 out of the gulag, 0 from the pool"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Bravo/)).toBeInTheDocument();
  });

  // Ben's ruling: a champion the directory cannot name is a manager who has left, which is
  // what "Former manager" says. "Unlisted" read as a hole in the data.
  it("calls a champion it could not resolve a former manager", () => {
    render(
      <SeasonCard
        season={{ ...SEASON, championLabel: null }}
        labelForMember={() => "Bravo"}
      />,
    );
    expect(screen.getByText("Former manager")).toBeInTheDocument();
    expect(screen.queryByText("Unlisted")).not.toBeInTheDocument();
  });

  it("says a week the sheet named was a former manager, not a week of counts", () => {
    // The sheet recorded a person that week, so the line is about a person either way; falling
    // back to the counts would report a different kind of week, and this one has no counts.
    const line = renderOneLine({
      week: 4,
      order: 1,
      memberId: 7,
      gulagOut: null,
      poolOut: null,
    });
    expect(line).toHaveTextContent("Week 4 · Former manager eliminated");
    expect(line.textContent).not.toContain("not recorded");
  });

  // Ben's ruling: a line is built from the figures the sheet actually wrote. Never a `0` where
  // a figure is missing — that is a week where nobody went out, a different fact — and never a
  // bare dash, which reads as the number itself.
  it("writes a 2023 row from its gulag count alone, with no pool clause", () => {
    // 2023 ran without a general pool, so `_eliminations_2023` writes `pool_out: null` for
    // every week of the season. A "pool not recorded" on all seven of them would report a hole
    // the file does not have.
    const line = renderOneLine({
      week: 11,
      order: 1,
      memberId: null,
      gulagOut: 4,
      poolOut: null,
    });
    expect(line).toHaveTextContent("Week 11 · 4 out of the gulag");
    expect(line.textContent).not.toContain("pool");
    expect(line.textContent).not.toContain("0");
    expect(line.textContent).not.toContain("—");
  });

  it("writes an uncached 2024 row from its pool count alone", () => {
    const line = renderOneLine({
      week: 5,
      order: 1,
      memberId: null,
      gulagOut: null,
      poolOut: 3,
    });
    expect(line).toHaveTextContent("Week 5 · 3 from the pool");
    expect(line.textContent).not.toContain("gulag");
    expect(line.textContent).not.toContain("0");
    expect(line.textContent).not.toContain("—");
  });

  it("says a week with neither figure is not recorded, rather than showing zeroes", () => {
    const line = renderOneLine({
      week: 6,
      order: 1,
      memberId: null,
      gulagOut: null,
      poolOut: null,
    });
    expect(line).toHaveTextContent("Week 6 · not recorded");
    expect(line.textContent).not.toContain("0");
    expect(line.textContent).not.toContain("—");
  });

  // The type carried a `remaining` figure the loader has never written: both workbook grids
  // hold the surviving-team column as an uncached formula, so no row can state one.
  it("never writes a remaining count", () => {
    render(<SeasonCard season={SEASON} labelForMember={() => null} />);
    fireEvent.click(screen.getByRole("button", { name: /eliminations/i }));
    expect(screen.queryByText(/remaining/i)).not.toBeInTheDocument();
  });
});
