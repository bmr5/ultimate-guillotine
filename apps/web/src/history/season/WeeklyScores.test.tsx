import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { weekRecord } from "./fixtures.test-support";
import type { WeeklyTeam } from "./types";
import { WeeklyScores } from "./WeeklyScores";

const state = vi.hoisted(() => ({
  data: [] as WeeklyTeam[],
  isPending: false,
  isError: false,
  refetch: vi.fn(),
  requested: vi.fn(),
}));
vi.mock("./useWeeklyRosters", () => ({
  useWeeklyRosters: (id: number | undefined) => {
    state.requested(id);
    return state;
  },
}));
const team = (id: number, points: number): WeeklyTeam => ({
  team_id: id,
  team_label: `Saved team ${id}`,
  manager_label: "Manager",
  points,
  roster_at: "2026-09-15T03:22:00Z",
  roster_coverage: "complete",
  players: [
    {
      player_id: "old-player",
      player_label: "Saved player",
      position: "RB",
      slot: "starter",
      started: true,
      owned_at_cutoff: true,
      points: 0,
    },
    {
      player_id: "bench",
      player_label: "Bench player",
      position: "WR",
      slot: "bench",
      started: false,
      owned_at_cutoff: true,
      points: null,
    },
  ],
});
beforeEach(() => {
  state.data = [];
  state.isPending = false;
  state.isError = false;
  vi.clearAllMocks();
});

describe("weekly scores", () => {
  it("sorts by score with tied ranks and exposes the frozen roster with zero distinct from missing points", () => {
    state.data = [team(1, 50), team(2, 150), team(3, 150)];
    const { container } = render(
      <WeeklyScores record={weekRecord()} events={[]} />,
    );
    const rows = container.querySelectorAll("details");
    expect(
      within(rows[0] as HTMLElement).getByText("Saved team 2"),
    ).toBeInTheDocument();
    expect(screen.getAllByLabelText("Rank 1")).toHaveLength(2);
    expect(screen.getByLabelText("Rank 3")).toBeInTheDocument();
    expect(rows[0].querySelector("summary")).toBeTruthy();
    // Native details supplies keyboard and click expansion without custom state.
    rows[0].open = true;
    expect(within(rows[0] as HTMLElement).getByText("0.00")).toBeVisible();
    expect(
      within(rows[0] as HTMLElement).getByLabelText("Points not recorded"),
    ).toBeVisible();
    expect(
      within(rows[0] as HTMLElement).getByText(/Sep 14, 10:22 PM CDT/),
    ).toBeVisible();
  });
  it("never requests finalized data for provisional or withdrawn weeks", () => {
    const { rerender } = render(
      <WeeklyScores
        record={weekRecord(1, { status: "provisional" })}
        events={[]}
      />,
    );
    expect(state.requested).toHaveBeenLastCalledWith(undefined);
    expect(screen.getByText(/when this week is confirmed/)).toBeInTheDocument();
    rerender(
      <WeeklyScores
        record={weekRecord(1, { status: "retracted" })}
        events={[]}
      />,
    );
    expect(screen.getByText(/result was withdrawn/)).toBeInTheDocument();
    expect(state.requested).toHaveBeenLastCalledWith(undefined);
  });
  it("uses the corrected revision and offers a retry when the archive request fails", () => {
    state.isError = true;
    render(
      <WeeklyScores
        record={weekRecord(1, { id: 22, revision: 2 })}
        events={[]}
      />,
    );
    expect(state.requested).toHaveBeenLastCalledWith(22);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(state.refetch).toHaveBeenCalledOnce();
    expect(screen.queryByText(/No team scores/)).toBeNull();
  });
});
