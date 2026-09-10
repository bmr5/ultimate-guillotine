import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RosterPlayer } from "../types";
import { DRAFTED_HERE_LABEL, draftedHereDescription } from "../derive/draft";
import { PlayerName } from "./PlayerName";

const player = (over: Partial<RosterPlayer> = {}): RosterPlayer => ({
  sleeperPlayerId: "9493",
  fullName: "Puka Nacua",
  position: "WR",
  nflTeam: "LAR",
  slot: "starter",
  slotIndex: 3,
  lineupPosition: "WR",
  projectedPoints: 14.1,
  livePoints: null,
  injuryStatus: null,
  draft: {
    teamId: 11,
    amount: 53,
    pickNo: 1,
    round: 1,
    position: "WR",
    draftedAt: "2026-09-07T23:01:30.433Z",
  },
  draftedHere: true,
  ...over,
});

describe("PlayerName", () => {
  it("is a button that opens a dialog for this player", () => {
    const onOpen = vi.fn();
    render(
      <PlayerName player={player()} ownerName="Ray Regime" onOpen={onOpen} />,
    );
    const name = screen.getByRole("button", { name: "Puka Nacua" });
    expect(name).toHaveAttribute("aria-haspopup", "dialog");
    fireEvent.click(name);
    expect(onOpen).toHaveBeenCalledWith("9493");
  });

  it("carries the mark, with the drafter and the price behind it, when he is still home", () => {
    render(
      <PlayerName player={player()} ownerName="Ray Regime" onOpen={vi.fn()} />,
    );
    const mark = screen.getByRole("button", { name: DRAFTED_HERE_LABEL });
    expect(mark).toHaveAttribute("data-drafted-here");
    expect(mark).toHaveAccessibleDescription(
      draftedHereDescription("Ray Regime", 53),
    );
  });

  it("carries no mark for a player another team drafted", () => {
    render(
      <PlayerName
        player={player({ draftedHere: false })}
        ownerName="Ray Regime"
        onOpen={vi.fn()}
      />,
    );
    expect(
      screen.queryByRole("button", { name: DRAFTED_HERE_LABEL }),
    ).not.toBeInTheDocument();
  });

  it("carries no mark for an undrafted pickup", () => {
    render(
      <PlayerName
        player={player({ draft: null, draftedHere: false })}
        ownerName="Ray Regime"
        onOpen={vi.fn()}
      />,
    );
    expect(
      screen.queryByRole("button", { name: DRAFTED_HERE_LABEL }),
    ).not.toBeInTheDocument();
  });
});
