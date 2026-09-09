import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { positionView } from "../derive/position";
import type { BoardTeam, RosterPlayer } from "../types";
import { LIKELY_BIDDER_LABEL, PositionView } from "./PositionView";

/** The league's own lineup, as `seasons.roster_positions` spells it. */
const LEAGUE_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"];

/** The narrowest phone the board is built for; every case renders at it. */
const PHONE_WIDTH = 375;

const player = (
  over: Partial<RosterPlayer> & { sleeperPlayerId: string; fullName: string },
): RosterPlayer => ({
  position: "TE",
  nflTeam: "KC",
  slot: "bench",
  slotIndex: null,
  lineupPosition: null,
  projectedPoints: null,
  ...over,
});

const team = (over: Partial<BoardTeam> & { teamId: number }): BoardTeam => ({
  teamName: `Team ${over.teamId}`,
  ownerName: `owner${over.teamId}`,
  sleeperRosterId: over.teamId,
  projectedPoints: 100,
  coveragePct: 100,
  isProvisional: false,
  projectionComputedAt: null,
  faabRemaining: 50,
  pointsFor: 100,
  startersProjected: 9,
  starterSlots: 9,
  isEliminated: false,
  eliminatedWeek: null,
  eliminationSource: null,
  emptySlots: null,
  isRosterFrozen: false,
  roster: [],
  ...over,
});

/** Ben's own case: one team stacked at tight end, one with none at all. */
const TEAMS: BoardTeam[] = [
  team({
    teamId: 1,
    ownerName: "Nick R",
    faabRemaining: 715,
    roster: [
      player({
        sleeperPlayerId: "kelce",
        fullName: "Travis Kelce",
        slot: "starter",
        slotIndex: 5,
        lineupPosition: "TE",
        projectedPoints: 14.1,
      }),
      player({
        sleeperPlayerId: "laporta",
        fullName: "Sam LaPorta",
        projectedPoints: 9.2,
      }),
      // A running back in the flex, so this team has no hole a tight end could fill.
      player({
        sleeperPlayerId: "gibbs",
        fullName: "Jahmyr Gibbs",
        position: "RB",
        slot: "starter",
        slotIndex: 6,
        lineupPosition: "FLEX",
        projectedPoints: 18.4,
      }),
    ],
  }),
  team({ teamId: 2, ownerName: "benray", faabRemaining: 40, roster: [] }),
];

const noop = () => undefined;
const noHighlights = new Set<string>();

interface RenderOptions {
  teams?: BoardTeam[];
  openTeamIds?: number[];
  onToggle?: (teamId: number) => void;
  highlightedPlayerIds?: ReadonlySet<string>;
}

function renderView({
  teams = TEAMS,
  openTeamIds = [],
  onToggle = noop,
  highlightedPlayerIds = noHighlights,
}: RenderOptions = {}) {
  const open = new Set(openTeamIds);
  return render(
    <PositionView
      position="TE"
      rows={positionView(teams, "TE", LEAGUE_SLOTS)}
      isOpen={(teamId) => open.has(teamId)}
      onToggle={onToggle}
      highlightedPlayerIds={highlightedPlayerIds}
      rosterPositions={LEAGUE_SLOTS}
    />,
  );
}

describe("PositionView", () => {
  beforeEach(() => {
    // jsdom lays nothing out, so the width is a statement of the case, not an assertion about
    // wrapping: what is tested at this width is that every row and control still renders and
    // that the taps stay on the 44px floor.
    window.innerWidth = PHONE_WIDTH;
  });

  it("gives every team a row with its owner, FAAB and players inline", () => {
    renderView();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("Nick R")).toBeInTheDocument();
    expect(screen.getByText("FAAB 715")).toBeInTheDocument();
    expect(screen.getByText("Travis Kelce")).toBeInTheDocument();
    expect(screen.getByText("Sam LaPorta")).toBeInTheDocument();
    expect(screen.getByText("14.1")).toBeInTheDocument();
    expect(screen.getByText("9.2")).toBeInTheDocument();
  });

  it("marks the starter at the position and leaves the bench unmarked", () => {
    renderView();
    const starter = screen.getByText("Travis Kelce").closest("[data-player]");
    const bench = screen.getByText("Sam LaPorta").closest("[data-player]");
    expect(starter).toHaveAttribute("data-starter");
    expect(bench).not.toHaveAttribute("data-starter");
  });

  it("says `no TE` in the warning style for a team without one", () => {
    renderView();
    const missing = screen.getByText("no TE");
    expect(missing).toBeInTheDocument();
    expect(missing.className).toContain("text-destructive");
  });

  it("counts the empty slots the position could fill", () => {
    renderView();
    // Team 2 starts nobody, so both the TE slot and the FLEX are holes a tight end fills.
    expect(screen.getByText("2 empty")).toBeInTheDocument();
  });

  it("badges the teams likely to bid", () => {
    renderView();
    const badges = screen.getAllByText(LIKELY_BIDDER_LABEL);
    expect(badges).toHaveLength(1);
    expect(badges[0].closest("li")).toHaveTextContent("benray");
  });

  it("keeps every tap on the 44px floor", () => {
    renderView();
    for (const button of screen.getAllByRole("button")) {
      expect(button.className).toContain("min-h-[44px]");
    }
  });

  it("expands a row into the team's full roster", () => {
    const onToggle = vi.fn();
    renderView({ onToggle });
    const toggle = screen.getByRole("button", { name: /Nick R/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // Collapsed, the roster panel is not mounted: this is a list of eighteen teams.
    expect(screen.queryByRole("list", { name: "Starters" })).toBeNull();

    fireEvent.click(toggle);
    expect(onToggle).toHaveBeenCalledWith(1);
  });

  it("shows the whole roster, empty slots and all, once a row is open", () => {
    renderView({ openTeamIds: [1] });
    expect(screen.getByRole("button", { name: /Nick R/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByRole("list", { name: "Starters" })).toBeInTheDocument();
    expect(screen.getByText("QB — Empty")).toBeInTheDocument();
    expect(screen.getByText("Bench")).toBeInTheDocument();
  });

  it("marks an eliminated team's row without fading its text", () => {
    const { container } = renderView({
      teams: [
        TEAMS[0],
        team({ teamId: 3, ownerName: "gone", isEliminated: true }),
      ],
    });
    const rows = screen.getAllByRole("listitem");
    // Eliminated last, whatever its FAAB.
    expect(rows[1]).toHaveTextContent("gone");
    expect(container.querySelectorAll("[data-eliminated]")).toHaveLength(1);
    expect(screen.getByText("gone")).toBeVisible();
  });

  it("highlights the players a search matched", () => {
    renderView({ highlightedPlayerIds: new Set(["kelce"]) });
    expect(
      screen.getByText("Travis Kelce").closest("[data-player]"),
    ).toHaveAttribute("data-highlighted");
    expect(
      screen.getByText("Sam LaPorta").closest("[data-player]"),
    ).not.toHaveAttribute("data-highlighted");
  });

  it("says FAAB — rather than a zero for a team with no state row", () => {
    renderView({
      teams: [team({ teamId: 4, ownerName: "stateless", faabRemaining: null })],
    });
    expect(screen.getByText("FAAB —")).toBeInTheDocument();
  });
});
