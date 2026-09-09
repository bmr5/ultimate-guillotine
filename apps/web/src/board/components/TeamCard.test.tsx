import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BoardTeam, RosterPlayer } from "../types";
import { TEAM_CARD_CLASS, TeamCard } from "./TeamCard";

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

interface RenderOptions {
  /** The card's open state; the board owns it, so every test states it outright. */
  open?: boolean;
  highlightedPlayerIds?: ReadonlySet<string>;
  onToggle?: (teamId: number) => void;
}

/**
 * The one place a card is mounted. The `<ul>` wrapper is the board's, not the card's — `TeamCard`
 * renders an `<li>` — and every test differs only in the team overrides and the open state.
 */
const renderCard = (
  overrides: Partial<BoardTeam> = {},
  { open = false, highlightedPlayerIds = noHighlights, onToggle = noop }: RenderOptions = {},
) =>
  render(
    <ul>
      <TeamCard
        team={team(overrides)}
        rank={1}
        isOpen={open}
        onToggle={onToggle}
        highlightedPlayerIds={highlightedPlayerIds}
      />
    </ul>,
  );

const toggleButton = () => screen.getByRole("button", { name: /benray/i });

interface StateCase {
  name: string;
  team: Partial<BoardTeam>;
  open?: boolean;
  /** Text the state must show. */
  present: (string | RegExp)[];
  /** Text the state must not show — the wrong renderings, spelled out. */
  absent?: (string | RegExp)[];
}

/**
 * Every projection, elimination and roster state the card renders, as one table. The assertions
 * are text-level on purpose: this is what a reader sees, and it survives restyling.
 */
const STATE_CASES: StateCase[] = [
  {
    name: "at or above the coverage gate: a bare number, no caveat",
    team: {},
    present: ["112.4"],
    absent: ["Partial projection coverage", "Projection unavailable"],
  },
  {
    name: "no projection row: an em dash and a caveat, never a zero",
    team: { projectedPoints: null, coveragePct: null, isProvisional: true },
    present: ["—", "Projection unavailable"],
    absent: ["0.0", "112.4"],
  },
  {
    name: "below the gate: the number stays, with a partial caveat beside it",
    team: { projectedPoints: 80, coveragePct: 66.7, isProvisional: true },
    present: ["80.0", "Partial projection coverage"],
    absent: ["Projection unavailable"],
  },
  {
    name: "eliminated with a known week: the week is named plainly",
    team: {
      isEliminated: true,
      eliminatedWeek: 4,
      eliminationSource: "adjudicator",
    },
    present: ["Eliminated week 4"],
  },
  {
    // `eliminated_week` is nullable: a provisional elimination can be known without its week.
    name: "eliminated with an unknown week: a bare Eliminated, not week null",
    team: {
      isEliminated: true,
      eliminatedWeek: null,
      eliminationSource: "sleeper_inferred",
    },
    present: ["Eliminated"],
    absent: [/Eliminated week/],
  },
  {
    name: "frozen roster: said once, above the roster",
    team: {
      isEliminated: true,
      eliminatedWeek: 4,
      eliminationSource: "adjudicator",
      isRosterFrozen: true,
    },
    open: true,
    present: ["Final roster, frozen at elimination", "Patrick Mahomes"],
  },
  {
    name: "empty roster: the waiting-for-sync line, not an empty box",
    team: { roster: [] },
    open: true,
    present: ["No roster rows yet — waiting for the first sync."],
    absent: ["Starters", "Patrick Mahomes"],
  },
  {
    name: "player with no projection: an em dash on the row",
    team: {
      roster: [
        player({
          sleeperPlayerId: "9",
          fullName: "Nobody",
          projectedPoints: null,
        }),
      ],
    },
    open: true,
    present: ["Nobody", "—"],
    absent: ["0.0"],
  },
];

describe("TeamCard states", () => {
  it.each(STATE_CASES)("$name", ({ team: overrides, open, present, absent }) => {
    renderCard(overrides, { open: open ?? false });
    for (const text of present) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    for (const text of absent ?? []) {
      expect(screen.queryByText(text)).not.toBeInTheDocument();
    }
  });
});

describe("TeamCard", () => {
  it("shows owner, team, projection, FAAB and record", () => {
    renderCard();
    expect(screen.getByText("benray")).toBeInTheDocument();
    expect(screen.getByText("The Choppers")).toBeInTheDocument();
    expect(screen.getByText("112.4")).toBeInTheDocument();
    // FAAB is a Sleeper waiver budget, not money: no dollar sign anywhere on the card.
    expect(screen.getByText(/\b75 FAAB\b/)).toBeInTheDocument();
    expect(screen.queryByText(/\$/)).toBeNull();
    expect(screen.getByText(/2-1/)).toBeInTheDocument();
    expect(screen.getByText(/301\.5 PF/)).toBeInTheDocument();
  });

  it("gives the summary toggle the same focus ring as the header controls", () => {
    // The one keyboard stop on a card. It is a bare <button>, not a `Button`, so it does not
    // inherit the shared ring and had none at all.
    renderCard();
    const className = toggleButton().className;
    expect(className).toContain("focus-visible:ring-2");
    expect(className).toContain("focus-visible:ring-ring");
    expect(className).toContain("focus-visible:ring-offset-2");
  });

  it("carries the class the scoped reduced-motion rule hangs off", () => {
    const { container } = renderCard();
    // Renaming TEAM_CARD_CLASS without editing globals.css would un-scope that rule silently.
    expect(container.querySelector(`.${TEAM_CARD_CLASS}`)).not.toBeNull();
  });

  it("wires the toggle button to the roster panel", () => {
    const onToggle = vi.fn();
    renderCard({}, { onToggle });
    const toggle = toggleButton();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle.getAttribute("aria-controls")).toBeTruthy();
    fireEvent.click(toggle);
    expect(onToggle).toHaveBeenCalledWith(7);
  });

  // The panel element is force-mounted so `aria-controls` points at something real, but its
  // contents are not: a board of collapsed cards must not carry every team's roster in the DOM.
  it("keeps the panel id resolvable while collapsed but mounts no roster rows", () => {
    const { container } = renderCard({
      roster: [
        player({ sleeperPlayerId: "4046" }),
        player({ sleeperPlayerId: "9", fullName: "Nobody", slotIndex: 1 }),
      ],
    });
    const panelId = toggleButton().getAttribute("aria-controls");
    expect(panelId).toBeTruthy();

    const panel = container.ownerDocument.getElementById(panelId as string);
    expect(panel).not.toBeNull();
    expect(panel).toHaveAttribute("hidden");

    expect(panel?.querySelectorAll("li")).toHaveLength(0);
    expect(screen.queryByText("Patrick Mahomes")).not.toBeInTheDocument();
    expect(screen.queryByText("Nobody")).not.toBeInTheDocument();
    expect(screen.queryByText("Starters")).not.toBeInTheDocument();
  });

  it("renders the roster under its slot label when open", () => {
    renderCard({}, { open: true });
    expect(toggleButton()).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Starters")).toBeInTheDocument();
    // The slot label is a plain label element, not a heading: a dozen cards' worth of <h4>s
    // would otherwise flood the page's heading outline.
    expect(screen.queryByRole("heading", { name: "Starters" })).toBeNull();
    expect(screen.getByRole("list", { name: "Starters" })).toBeInTheDocument();
    expect(screen.getByText("Patrick Mahomes")).toBeInTheDocument();
    expect(screen.getByText("QB · KC")).toBeInTheDocument();
    expect(screen.getByText("22.6")).toBeInTheDocument();
  });

  it("marks only the rows a search matched", () => {
    renderCard(
      {
        roster: [
          player({ sleeperPlayerId: "4046" }),
          player({ sleeperPlayerId: "9", fullName: "Nobody", slotIndex: 1 }),
        ],
      },
      { open: true, highlightedPlayerIds: new Set(["4046"]) },
    );
    expect(screen.getByText("Patrick Mahomes").closest("li")).toHaveAttribute(
      "data-highlighted",
    );
    expect(screen.getByText("Nobody").closest("li")).not.toHaveAttribute(
      "data-highlighted",
    );
  });

  it("leaves every row unmarked when nothing is searched for", () => {
    const { container } = renderCard({}, { open: true });
    expect(container.querySelectorAll("[data-highlighted]")).toHaveLength(0);
  });

  // Elimination is asserted through the badge and `data-eliminated`, never a utility class: the
  // card used to fade its own text with `opacity-60`, and the fix is a styling change the test
  // must not pin down beyond "the state is still legible from the outside".
  it("marks an eliminated card without fading its text", () => {
    const { container } = renderCard({
      isEliminated: true,
      eliminatedWeek: 4,
      eliminationSource: "adjudicator",
    });
    expect(screen.getByText("Eliminated week 4")).toBeInTheDocument();
    expect(container.querySelector("[data-eliminated]")).not.toBeNull();
    // The owner and the projection are still ordinary card text, not a faded copy of it.
    expect(screen.getByText("benray")).toBeVisible();
    expect(screen.getByText("112.4")).toBeVisible();
  });

  it("leaves a live card unmarked", () => {
    const { container } = renderCard();
    expect(container.querySelector("[data-eliminated]")).toBeNull();
    expect(screen.queryByText(/Eliminated/)).not.toBeInTheDocument();
  });

  it("puts a provisional ruling in a tooltip, not in the label", () => {
    renderCard({
      isEliminated: true,
      eliminatedWeek: 4,
      eliminationSource: "sleeper_inferred",
    });
    expect(screen.getByText("Eliminated week 4")).toHaveAttribute(
      "title",
      expect.stringContaining("Provisional"),
    );
  });

  it("leaves an adjudicator ruling untooltipped and still expandable", () => {
    renderCard(
      {
        isEliminated: true,
        eliminatedWeek: 4,
        eliminationSource: "adjudicator",
        isRosterFrozen: true,
      },
      { open: true },
    );
    expect(toggleButton()).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Eliminated week 4")).not.toHaveAttribute("title");
    expect(screen.getByText("Patrick Mahomes")).toBeInTheDocument();
  });

  it("dates the partial caveat in words, never as an ISO string", () => {
    renderCard({ projectedPoints: 80, coveragePct: 66.7, isProvisional: true });
    const badge = screen
      .getByText("Partial projection coverage")
      .closest("[title]");
    expect(badge).not.toBeNull();
    const title = badge?.getAttribute("title") ?? "";
    expect(title).toMatch(/^Computed /);
    expect(title).not.toMatch(/\d{4}-\d{2}-\d{2}T/);
  });

  it("does not date a projection that was never computed", () => {
    renderCard({
      projectedPoints: null,
      coveragePct: null,
      isProvisional: true,
    });
    expect(screen.getByText("Projection unavailable")).not.toHaveAttribute(
      "title",
    );
  });
});
