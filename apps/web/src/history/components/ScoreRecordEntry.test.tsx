import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ScoreRecordRoster } from "../useScoreRecordRoster";
import { ScoreRecordEntry } from "./ScoreRecordEntry";

const state = vi.hoisted(() => ({
  data: null as ScoreRecordRoster | null,
  isPending: false,
  isError: false,
  refetch: vi.fn(),
  requested: vi.fn(),
}));
vi.mock("../useScoreRecordRoster", () => ({
  useScoreRecordRoster: (key: string) => {
    state.requested(key);
    return state;
  },
}));
const record = {
  key: "sleeper:2023:7:1",
  season: 2023,
  week: 7,
  team_label: "Saved team",
  manager_label: "Ben R",
  points: 22.5,
  rank: 1,
};
beforeEach(() => {
  state.data = null;
  state.isPending = false;
  state.isError = false;
  vi.clearAllMocks();
});
function show() {
  render(
    <MemoryRouter>
      <ul>
        <ScoreRecordEntry record={record} leading />
      </ul>
    </MemoryRouter>,
  );
}
describe("score roster popup", () => {
  it("loads only on open and shows the scoring lineup, empty slots and separate bench", () => {
    state.data = {
      ...record,
      roster_at: null,
      roster: {
        starters: [
          {
            player_id: "1",
            player_label: "Starting player",
            slot: "RB",
            position: "RB",
            points: 22.5,
          },
          {
            player_id: "2",
            player_label: "Zero scorer",
            slot: "WR",
            position: "WR",
            points: 0,
          },
          {
            player_id: null,
            player_label: "Empty slot",
            slot: "QB",
            position: null,
            points: 0,
          },
        ],
        bench: [
          {
            player_id: "3",
            player_label: "Bench player",
            slot: "Bench",
            position: "TE",
            points: 40,
          },
        ],
      },
    };
    show();
    expect(state.requested).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /View roster: Ben R/ }));
    expect(state.requested).toHaveBeenCalledWith(record.key);
    const popup = screen.getByRole("dialog");
    expect(
      within(popup).getByText("2 of 3 starting slots filled"),
    ).toBeVisible();
    const starters = within(popup).getByRole("table", {
      name: "Starting lineup",
    });
    expect(within(starters).getByText("Empty slot")).toBeVisible();
    expect(within(starters).getByText("0.00")).toBeVisible();
    expect(within(starters).queryByText("Bench player")).toBeNull();
    expect(
      within(popup).getByRole("table", {
        name: "Bench · not included in team score",
      }),
    ).toHaveTextContent("40.00");
    fireEvent.click(within(popup).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  it("shows a retry for a failed roster request", () => {
    state.isError = true;
    show();
    fireEvent.click(screen.getByRole("button", { name: /View roster/ }));
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(state.refetch).toHaveBeenCalledOnce();
    expect(screen.queryByRole("table")).toBeNull();
  });
  it("does not invent a roster when a record is missing or withdrawn", () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: /View roster/ }));
    expect(screen.getByText(/saved roster is unavailable/)).toBeVisible();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
