import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WeeklyScoreRecords as Records } from "../useWeeklyScoreRecords";
import { WeeklyScoreRecords } from "./WeeklyScoreRecords";

const state = vi.hoisted(() => ({
  data: undefined as Records | undefined,
  isPending: false,
  isError: false,
  refetch: vi.fn(),
}));
vi.mock("../useWeeklyScoreRecords", () => ({
  useWeeklyScoreRecords: () => state,
}));
vi.mock("../useScoreRecordRoster", () => ({
  useScoreRecordRoster: () => ({
    data: null,
    isPending: false,
    isError: false,
  }),
}));
beforeEach(() => {
  state.data = undefined;
  state.isPending = false;
  state.isError = false;
  vi.clearAllMocks();
});
function show() {
  return render(
    <MemoryRouter>
      <WeeklyScoreRecords />
    </MemoryRouter>,
  );
}
describe("weekly score records", () => {
  it("expands each card independently to ten and collapses back to five", () => {
    const rows = Array.from({ length: 10 }, (_, index) => ({
      key: String(index),
      rank: index + 1,
      season: 2024,
      week: index + 1,
      team_label: `Team ${index}`,
      manager_label: `Manager ${index}`,
      points: 100 + index,
    }));
    state.data = {
      highs: rows,
      lows: rows,
      full_lineup_lows: rows.map((row, index) => ({
        ...row,
        key: `full-${index}`,
        manager_label: `Full manager ${index}`,
      })),
      coverage: [{ season: 2024, weeks: 10, scores: 10 }],
    };
    show();
    for (const title of ["Highest weekly scores", "Lowest weekly scores"]) {
      const list = screen.getByRole("list", { name: title });
      expect(within(list).getAllByRole("listitem")).toHaveLength(5);
      const button = screen.getByRole("button", {
        name: `Show top 10: ${title}`,
      });
      expect(button).toHaveAttribute("aria-controls", list.id);
      fireEvent.click(button);
      expect(within(list).getAllByRole("listitem")).toHaveLength(10);
      expect(button).toHaveAttribute("aria-expanded", "true");
      for (const other of screen
        .getAllByRole("list")
        .filter((item) => item !== list)) {
        expect(within(other).getAllByRole("listitem")).toHaveLength(5);
      }
      fireEvent.click(
        screen.getByRole("button", { name: `Show less: ${title}` }),
      );
      expect(within(list).getAllByRole("listitem")).toHaveLength(5);
      expect(button).toHaveAttribute("aria-expanded", "false");
    }
    expect(screen.getAllByRole("list")).toHaveLength(2);
    const lows = screen.getByRole("list", { name: "Lowest weekly scores" });
    fireEvent.click(
      screen.getByRole("button", { name: "Show top 10: Lowest weekly scores" }),
    );
    const toggle = screen.getByRole("switch", { name: "Full lineups only" });
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);
    expect(toggle).toBeChecked();
    expect(within(lows).getAllByRole("listitem")).toHaveLength(10);
    expect(within(lows).getByText("Full manager 9")).toBeVisible();
    fireEvent.click(toggle);
    expect(within(lows).getByText("Manager 9")).toBeVisible();
    expect(within(lows).getAllByRole("listitem")).toHaveLength(10);
  });
  it("keeps all boundary ties when collapsed and expanded", () => {
    const rows = [1, 2, 3, 4, 5, 5, 7, 8, 9, 10, 10].map((rank, index) => ({
      key: String(index),
      rank,
      season: 2024,
      week: 1,
      team_label: `Team ${index}`,
      manager_label: null,
      points: 100 - rank,
    }));
    state.data = {
      highs: rows,
      lows: [],
      full_lineup_lows: [],
      coverage: [{ season: 2024, weeks: 1, scores: 11 }],
    };
    show();
    const list = screen.getByRole("list", { name: "Highest weekly scores" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(6);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Show top 10: Highest weekly scores",
      }),
    );
    expect(within(list).getAllByRole("listitem")).toHaveLength(11);
    expect(screen.getAllByRole("button", { name: /^Show / })).toHaveLength(1);
  });
  it("shows score, manager, season and week with explicit archive coverage", () => {
    const record = {
      key: "a",
      rank: 1,
      season: 2024,
      week: 15,
      team_label: "High team",
      manager_label: "High manager",
      points: 192.9,
    };
    state.data = {
      highs: [record],
      full_lineup_lows: [
        {
          ...record,
          key: "full",
          points: 44.86,
          manager_label: "Full lineup manager",
        },
      ],
      lows: [
        {
          ...record,
          key: "b",
          season: 2026,
          week: 1,
          points: 0,
          manager_label: "Low manager",
        },
      ],
      coverage: [
        { season: 2024, weeks: 17, scores: 193 },
        { season: 2026, weeks: 1, scores: 18 },
      ],
    };
    show();
    const highs = screen.getByRole("list", { name: "Highest weekly scores" });
    expect(within(highs).getByText("192.90")).toBeVisible();
    expect(within(highs).getByText("High manager")).toBeVisible();
    expect(within(highs).getByText("2024 · Week 15")).toBeVisible();
    expect(screen.getByText("0.00")).toBeVisible();
    fireEvent.click(screen.getByRole("switch", { name: "Full lineups only" }));
    const full = screen.getByRole("list", { name: "Lowest weekly scores" });
    expect(within(full).getByText("44.86")).toBeVisible();
    expect(within(full).queryByText("0.00")).toBeNull();
    expect(
      screen.getByText(/Players on bye or out injured still count/),
    ).toBeVisible();
    expect(
      screen.getByText(/Earlier seasons aren't available yet/),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("switch", { name: "Full lineups only" }));
    fireEvent.click(
      screen.getByRole("button", {
        name: "View roster: Low manager, 2026 Week 1, 0.00 points",
      }),
    );
    expect(
      screen.getByRole("link", { name: "View all teams in 2026 · Week 1" }),
    ).toHaveAttribute("href", "/current-season?week=1");
  });
  it("shows a recoverable failure without inventing records", () => {
    state.isError = true;
    show();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(state.refetch).toHaveBeenCalledOnce();
    expect(screen.queryByRole("list")).toBeNull();
  });
  it("distinguishes loading from an empty archive", () => {
    state.isPending = true;
    const view = show();
    expect(screen.getByRole("status")).toBeVisible();
    state.isPending = false;
    state.data = { highs: [], lows: [], full_lineup_lows: [], coverage: [] };
    view.rerender(
      <MemoryRouter>
        <WeeklyScoreRecords />
      </MemoryRouter>,
    );
    expect(
      screen.getByText("No confirmed weekly scores are available yet."),
    ).toBeVisible();
  });
});
