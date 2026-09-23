import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  eventRecord,
  weekRecord,
} from "@/history/season/fixtures.test-support";
import type { SeasonArchive } from "@/history/season/types";

import { CurrentSeasonPage } from "./CurrentSeasonPage";

const state = vi.hoisted(() => ({
  archive: { weeks: [], events: [] } as SeasonArchive,
  pending: false,
  error: false,
  refetch: vi.fn(),
}));
vi.mock("@/history/season/useSeasonArchive", () => ({
  useSeasonArchive: () => ({
    data: state.archive,
    isPending: state.pending,
    isError: state.error,
    refetch: state.refetch,
  }),
  useEventPlayers: () => ({ data: [], isPending: false, isError: false }),
}));
vi.mock("@/history/season/useWeeklyRosters", () => ({
  useWeeklyRosters: () => ({ data: [], isPending: false, isError: false }),
}));
function renderPage(path = "/current-season?week=1&view=events") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <CurrentSeasonPage />
    </MemoryRouter>,
  );
}
beforeEach(() => {
  state.archive = { weeks: [], events: [] };
  state.pending = false;
  state.error = false;
});

describe("Current season page", () => {
  it("opens scores by default and keeps the selected week when switching views", () => {
    renderPage("/current-season?week=1");
    expect(
      screen.getByRole("button", { name: "Scores & rosters" }),
    ).toHaveAttribute("aria-pressed", "true");
    fireEvent.change(screen.getByRole("combobox", { name: "Week" }), {
      target: { value: "2" },
    });
    expect(
      screen.getByRole("region", { name: "Week 2 history" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Gulag & cuts" }));
    expect(screen.getByRole("combobox", { name: "Week" })).toHaveValue("2");
    expect(
      screen.getByRole("button", { name: "Gulag & cuts" }),
    ).toHaveAttribute("aria-pressed", "true");
  });
  it("shows the current season and scheduled timeline without fabricating results", () => {
    renderPage();
    expect(screen.getByText("Current season · 2026")).toBeInTheDocument();
    expect(screen.getByText("Awaiting results")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Week 1:.*18 teams scheduled/ }),
    ).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(
      screen.getByRole("button", { name: /Week 12: Double cut/ }),
    );
    expect(
      screen.getByRole("region", { name: "Week 12 history" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/The last gulag loser and the lowest eligible/),
    ).toBeInTheDocument();
  });
  it("shows Week 1 gulag events and explains why the cuts filter is empty", () => {
    state.archive = {
      weeks: [weekRecord()],
      events: [eventRecord(1), eventRecord(2)],
    };
    renderPage();
    expect(screen.getAllByText("Qualified for gulag")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Cuts & champion" }));
    expect(
      screen.getByText("Nobody was cut in Week 1. All 18 teams remain alive."),
    ).toBeInTheDocument();
  });
  it("opens a saved substitution snapshot and shows unknown money instead of $0", () => {
    state.archive = {
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
      ],
    };
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /Entered gulag: Max/ }));
    expect(
      screen.getByText("Original qualifier: Ben. Actual participant: Max."),
    ).toBeInTheDocument();
    expect(screen.getByText("Not recorded")).toBeInTheDocument();
    expect(screen.queryByText("$0")).toBeNull();
  });
  it("shows errors with a retry instead of an empty recorded history", () => {
    state.error = true;
    renderPage();
    expect(
      screen.getByText("Could not load current season"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Awaiting results")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(state.refetch).toHaveBeenCalled();
  });
  it("labels provisional events and never presents them as confirmed", () => {
    state.archive = {
      weeks: [weekRecord(1, { status: "provisional" })],
      events: [eventRecord(1), eventRecord(2)],
    };
    renderPage();
    expect(screen.getAllByText("Qualified for gulag · Not final")).toHaveLength(
      2,
    );
    expect(
      screen.getByText(/Totals cover 0 confirmed weeks/),
    ).toBeInTheDocument();
  });
});
