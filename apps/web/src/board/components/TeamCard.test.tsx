import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BoardTeam, RosterPlayer } from "../types";
import { TeamCard } from "./TeamCard";

const player = (
  over: Partial<RosterPlayer> & { sleeperPlayerId: string },
): RosterPlayer => ({
  fullName: "Patrick Mahomes",
  position: "QB",
  nflTeam: "KC",
  slot: "starter",
  slotIndex: 0,
  lineupPosition: "QB",
  projectedPoints: 22.6,
  ...over,
});

const team = (over: Partial<BoardTeam> = {}): BoardTeam => ({
  isRosterFrozen: false,
  teamId: 7,
  teamName: "The Choppers",
  ownerName: "benray",
  sleeperRosterId: 1,
  projectedPoints: 112.4,
  coveragePct: 100,
  isProvisional: false,
  projectionComputedAt: "2026-09-09T12:00:00Z",
  faabRemaining: 75,
  wins: 2,
  losses: 1,
  ties: 0,
  pointsFor: 301.5,
  isEliminated: false,
  eliminatedWeek: null,
  eliminationSource: null,
  roster: [player({ sleeperPlayerId: "4046" })],
  ...over,
});

const noop = () => undefined;
const noHighlights = new Set<string>();

describe("TeamCard", () => {
  it("shows owner, team, projection, FAAB and record", () => {
    render(
      <ul>
        <TeamCard
          team={team()}
          rank={1}
          isOpen={false}
          onToggle={noop}
          highlightedPlayerIds={noHighlights}
        />
      </ul>,
    );
    expect(screen.getByText("benray")).toBeInTheDocument();
    expect(screen.getByText("The Choppers")).toBeInTheDocument();
    expect(screen.getByText("112.4")).toBeInTheDocument();
    expect(screen.getByText(/\$75 FAAB/)).toBeInTheDocument();
    expect(screen.getByText(/2-1/)).toBeInTheDocument();
    expect(screen.getByText(/301\.5 PF/)).toBeInTheDocument();
  });

  it("wires the toggle button to the roster panel", () => {
    const onToggle = vi.fn();
    render(
      <ul>
        <TeamCard
          team={team()}
          rank={1}
          isOpen={false}
          onToggle={onToggle}
          highlightedPlayerIds={noHighlights}
        />
      </ul>,
    );
    const toggle = screen.getByRole("button", { name: /benray/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle.getAttribute("aria-controls")).toBeTruthy();
    fireEvent.click(toggle);
    expect(onToggle).toHaveBeenCalledWith(7);
  });

  // The panel is force-mounted so `aria-controls` points at a real element even while the card
  // is collapsed; a dangling reference is an accessibility bug screen readers report as such.
  it("keeps the roster panel id resolvable while collapsed", () => {
    const { container } = render(
      <ul>
        <TeamCard
          team={team()}
          rank={1}
          isOpen={false}
          onToggle={noop}
          highlightedPlayerIds={noHighlights}
        />
      </ul>,
    );
    const toggle = screen.getByRole("button", { name: /benray/i });
    const panelId = toggle.getAttribute("aria-controls");
    expect(panelId).toBeTruthy();
    const panel = container.ownerDocument.getElementById(panelId as string);
    expect(panel).not.toBeNull();
    expect(panel).toHaveAttribute("hidden");
  });

  it("renders the roster with a starters heading when open", () => {
    render(
      <ul>
        <TeamCard
          team={team()}
          rank={1}
          isOpen
          onToggle={noop}
          highlightedPlayerIds={noHighlights}
        />
      </ul>,
    );
    expect(screen.getByRole("button", { name: /benray/i })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText("Starters")).toBeInTheDocument();
    expect(screen.getByText("Patrick Mahomes")).toBeInTheDocument();
    expect(screen.getByText("QB · KC")).toBeInTheDocument();
    expect(screen.getByText("22.6")).toBeInTheDocument();
  });

  it("renders an em dash and a caveat instead of a zero when the projection is missing", () => {
    render(
      <ul>
        <TeamCard
          team={team({
            projectedPoints: null,
            coveragePct: null,
            isProvisional: true,
          })}
          rank={1}
          isOpen={false}
          onToggle={noop}
          highlightedPlayerIds={noHighlights}
        />
      </ul>,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("Projection unavailable")).toBeInTheDocument();
    expect(screen.queryByText("0.0")).not.toBeInTheDocument();
  });

  it("badges partial coverage without hiding the number", () => {
    render(
      <ul>
        <TeamCard
          team={team({
            projectedPoints: 80,
            coveragePct: 66.7,
            isProvisional: true,
          })}
          rank={1}
          isOpen={false}
          onToggle={noop}
          highlightedPlayerIds={noHighlights}
        />
      </ul>,
    );
    expect(screen.getByText("80.0")).toBeInTheDocument();
    expect(screen.getByText("Partial projection coverage")).toBeInTheDocument();
  });

  it("dims an eliminated team and labels the week plainly", () => {
    const { container } = render(
      <ul>
        <TeamCard
          team={team({
            isEliminated: true,
            eliminatedWeek: 4,
            eliminationSource: "sleeper_inferred",
          })}
          rank={1}
          isOpen={false}
          onToggle={noop}
          highlightedPlayerIds={noHighlights}
        />
      </ul>,
    );
    const label = screen.getByText("Eliminated week 4");
    expect(label).toBeInTheDocument();
    // A provisional ruling is a tooltip, not extra label text.
    expect(label).toHaveAttribute(
      "title",
      expect.stringContaining("Provisional"),
    );
    expect(container.querySelector(".opacity-60")).not.toBeNull();
  });

  // `eliminated_week` is nullable: a provisional elimination can be known without its week.
  it("reads a bare Eliminated when the week is unknown", () => {
    render(
      <ul>
        <TeamCard
          team={team({
            isEliminated: true,
            eliminatedWeek: null,
            eliminationSource: "sleeper_inferred",
          })}
          rank={1}
          isOpen={false}
          onToggle={noop}
          highlightedPlayerIds={noHighlights}
        />
      </ul>,
    );
    expect(screen.getByText("Eliminated")).toBeInTheDocument();
    expect(screen.queryByText(/Eliminated week/)).not.toBeInTheDocument();
  });

  it("stays expandable when eliminated and shows the frozen roster", () => {
    render(
      <ul>
        <TeamCard
          team={team({
            isEliminated: true,
            eliminatedWeek: 4,
            eliminationSource: "adjudicator",
            isRosterFrozen: true,
          })}
          rank={1}
          isOpen
          onToggle={noop}
          highlightedPlayerIds={noHighlights}
        />
      </ul>,
    );
    expect(screen.getByRole("button", { name: /benray/i })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(
      screen.getByText("Final roster, frozen at elimination"),
    ).toBeInTheDocument();
    expect(screen.getByText("Patrick Mahomes")).toBeInTheDocument();
    expect(screen.getByText("Eliminated week 4")).not.toHaveAttribute("title");
  });

  it("shows an em dash for a player with no projection", () => {
    render(
      <ul>
        <TeamCard
          team={team({
            roster: [
              player({
                sleeperPlayerId: "9",
                fullName: "Nobody",
                projectedPoints: null,
              }),
            ],
          })}
          rank={1}
          isOpen
          onToggle={noop}
          highlightedPlayerIds={noHighlights}
        />
      </ul>,
    );
    expect(screen.getByText("Nobody")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
