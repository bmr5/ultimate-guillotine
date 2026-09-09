import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BoardTeam, RosterPlayer } from "../types";
import { TEAM_CARD_CLASS, TeamCard } from "./TeamCard";

/** The league's own lineup, as `seasons.roster_positions` spells it. */
const LEAGUE_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"];

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
  pointsFor: 301.5,
  startersProjected: 9,
  starterSlots: 9,
  isEliminated: false,
  eliminatedWeek: null,
  eliminationSource: null,
  emptySlots: null,
  roster: [player({ sleeperPlayerId: "4046" })],
  ...over,
});

/** A full lineup for `LEAGUE_SLOTS`: one starter per slot, in slot order. */
const fullLineup = (): RosterPlayer[] =>
  LEAGUE_SLOTS.map((position, index) =>
    player({
      sleeperPlayerId: `s${index}`,
      fullName: `Starter ${index}`,
      slotIndex: index,
      lineupPosition: position,
      position,
    }),
  );

/**
 * One turn of the macrotask queue. Radix registers the open tooltip's outside-pointerdown
 * listener from a `setTimeout(0)`, so a tap fired in the same tick as the open is not the tap a
 * reader makes — the layer that closes on pointerdown is not listening yet.
 */
const settle = () =>
  act(() => new Promise<void>((resolve) => setTimeout(resolve, 0)));

const noop = () => undefined;
const noHighlights = new Set<string>();

interface RenderOptions {
  /** The card's open state; the board owns it, so every test states it outright. */
  open?: boolean;
  highlightedPlayerIds?: ReadonlySet<string>;
  onToggle?: (teamId: number) => void;
  /**
   * The league's lineup. Empty by default — the shape before `seasons` has resolved, in which
   * every starter still renders and no slot can be called empty — so the cases about empty
   * slots name the lineup they are about.
   */
  rosterPositions?: string[];
}

/**
 * The one place a card is mounted. The `<ul>` wrapper is the board's, not the card's — `TeamCard`
 * renders an `<li>` — and every test differs only in the team overrides and the open state.
 */
const renderCard = (
  overrides: Partial<BoardTeam> = {},
  {
    open = false,
    highlightedPlayerIds = noHighlights,
    onToggle = noop,
    rosterPositions = [],
  }: RenderOptions = {},
) =>
  render(
    <ul>
      <TeamCard
        team={team(overrides)}
        rank={1}
        isOpen={open}
        onToggle={onToggle}
        highlightedPlayerIds={highlightedPlayerIds}
        rosterPositions={rosterPositions}
      />
    </ul>,
  );

const toggleButton = () => screen.getByRole("button", { name: /benray/i });

/** The `partial` badge under the projection; also the tooltip's trigger. */
const partialBadge = () =>
  screen.getByRole("button", { name: "Partial projection coverage" });

/** A team whose projection covers six of nine starters — the below-gate state. */
const partialTeam = (): Partial<BoardTeam> => ({
  projectedPoints: 80,
  coveragePct: 66.67,
  isProvisional: true,
  startersProjected: 6,
  starterSlots: 9,
});

/** The sentence Ben asked the badge to carry, spelled out once. */
const COVERAGE_SENTENCE =
  "Only 6 of 9 starters have a projection (66.7%). " +
  "The number counts the players Sleeper has projected.";

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
    name: "below the gate: the number stays, with a partial caveat under it",
    team: {
      projectedPoints: 80,
      coveragePct: 66.67,
      isProvisional: true,
      startersProjected: 6,
      starterSlots: 9,
    },
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
  it.each(STATE_CASES)(
    "$name",
    ({ team: overrides, open, present, absent }) => {
      renderCard(overrides, { open: open ?? false });
      for (const text of present) {
        expect(screen.getByText(text)).toBeInTheDocument();
      }
      for (const text of absent ?? []) {
        expect(screen.queryByText(text)).not.toBeInTheDocument();
      }
    },
  );
});

describe("TeamCard", () => {
  it("shows owner, team, projection, the season total and FAAB", () => {
    renderCard();
    expect(screen.getByText("benray")).toBeInTheDocument();
    expect(screen.getByText("The Choppers")).toBeInTheDocument();
    expect(screen.getByText("112.4")).toBeInTheDocument();
    // Ben's card change 1: the total leads the line, and FAAB follows it.
    expect(screen.getByText("Total 301.5")).toBeInTheDocument();
    // FAAB is a Sleeper waiver budget, not money: no dollar sign anywhere on the card.
    expect(screen.getByText(/\b75 FAAB\b/)).toBeInTheDocument();
    expect(screen.queryByText(/\$/)).toBeNull();
  });

  it("names the total in full for a reader who cannot see the line", () => {
    renderCard();
    expect(screen.getByText("Total points 301.5")).toBeInTheDocument();
    expect(screen.getByText("Total points 301.5").className).toContain(
      "sr-only",
    );
  });

  // Ben's card change 2: no record anywhere on the card — not the text, not a tooltip.
  it("shows no win-loss record at all", () => {
    const { container } = renderCard();
    expect(screen.queryByText(/\d+-\d+/)).toBeNull();
    expect(screen.queryByText(/ PF\b/)).toBeNull();
    expect(container.textContent).not.toMatch(/Points for/i);
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

  /**
   * The card lost whole-card tapping when the `partial` badge was given its own control inside
   * the summary row: the projection block stopped being part of the toggle, and the number is
   * the part of a card a thumb lands on. The summary is one button again, and the badge is a
   * sibling of it.
   */
  it("toggles the card from the projection number, not just the name", () => {
    const onToggle = vi.fn();
    // A partial team, so the badge is on the card while the number is tapped.
    renderCard(partialTeam(), { onToggle });
    fireEvent.click(screen.getByText("80.0"));
    expect(onToggle).toHaveBeenCalledWith(7);
  });

  it("keeps the projection block and the empty count inside the toggle", () => {
    const { container } = renderCard(
      {
        roster: [
          player({
            sleeperPlayerId: "4046",
            slotIndex: 0,
            lineupPosition: "QB",
          }),
        ],
      },
      { rosterPositions: LEAGUE_SLOTS },
    );
    const projection = container.querySelector("[data-projection]");
    expect(projection).not.toBeNull();
    expect(toggleButton().contains(projection)).toBe(true);
    expect(toggleButton()).toHaveTextContent("8 empty");
  });

  // A control inside a <button> is invalid HTML: the reason the summary was split in the first
  // place, and the thing that would break again if the badge were moved back inside it.
  it("nests no control inside the summary button", () => {
    renderCard(partialTeam());
    expect(toggleButton().querySelector("button, a, input, select")).toBeNull();
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
    renderCard(partialTeam());
    fireEvent.click(partialBadge());
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveTextContent(/Computed /);
    expect(tooltip.textContent ?? "").not.toMatch(/\d{4}-\d{2}-\d{2}T/);
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

/**
 * Ben's addendum 1: "sometimes teams don't have every roster spot filled. Nick R right now is
 * missing a flex — that's very important information." So every slot renders, empty or not, and
 * the count is on the collapsed card.
 */
describe("TeamCard empty starter slots", () => {
  const oneStarter = () => ({
    roster: [
      player({ sleeperPlayerId: "4046", slotIndex: 0, lineupPosition: "QB" }),
    ],
  });

  it("renders a row for every lineup slot and names the empty ones", () => {
    renderCard(oneStarter(), { open: true, rosterPositions: LEAGUE_SLOTS });
    expect(screen.getByText("Patrick Mahomes")).toBeInTheDocument();
    expect(screen.getByText("FLEX — Empty")).toBeInTheDocument();
    expect(screen.getAllByText(/ — Empty$/)).toHaveLength(8);
    // The starters section carries all nine lineup rows, not just the filled one.
    expect(
      screen.getByRole("list", { name: "Starters" }).querySelectorAll("li"),
    ).toHaveLength(9);
  });

  it("marks an empty row in the warning token rather than the muted one", () => {
    renderCard(oneStarter(), { open: true, rosterPositions: LEAGUE_SLOTS });
    const row = screen.getByText("FLEX — Empty").closest("li");
    expect(row).not.toBeNull();
    expect(row).toHaveAttribute("data-empty-slot");
    expect(row?.className).toContain("text-destructive");
  });

  it("badges the empty count on the collapsed card, beside the projection", () => {
    renderCard(oneStarter(), { rosterPositions: LEAGUE_SLOTS });
    expect(screen.getByText("8 empty")).toBeInTheDocument();
    // Visible without expanding: the count sits in the projection block, in the summary row.
    expect(
      screen.getByText("8 empty").closest("[data-projection]"),
    ).not.toBeNull();
  });

  it("prefers the data layer's own empty_slots count when the week has a projection", () => {
    renderCard(
      { ...oneStarter(), emptySlots: 3 },
      { rosterPositions: LEAGUE_SLOTS },
    );
    expect(screen.getByText("3 empty")).toBeInTheDocument();
    expect(screen.queryByText("8 empty")).toBeNull();
  });

  it("says nothing about empty slots when the lineup is full", () => {
    renderCard(
      { roster: fullLineup(), emptySlots: 0 },
      { open: true, rosterPositions: LEAGUE_SLOTS },
    );
    expect(screen.queryByText(/ empty$/)).toBeNull();
    expect(screen.queryByText(/ — Empty$/)).toBeNull();
    expect(
      screen.getByRole("list", { name: "Starters" }).querySelectorAll("li"),
    ).toHaveLength(9);
  });

  it("still renders every starter when the lineup is not known yet", () => {
    renderCard({ roster: fullLineup() }, { open: true });
    expect(
      screen.getByRole("list", { name: "Starters" }).querySelectorAll("li"),
    ).toHaveLength(9);
    expect(screen.queryByText(/ — Empty$/)).toBeNull();
    expect(screen.queryByText(/ empty$/)).toBeNull();
  });
});

/**
 * Ben's card change 3: "the partial badge should sit under the number it is about, and say why
 * it is there." So it moved into the projection block and grew a tooltip that names the two
 * figures behind the caveat.
 */
describe("TeamCard partial coverage badge", () => {
  it("renders the badge under the projection, outside the toggle button", () => {
    const { container } = renderCard(partialTeam());
    const badge = partialBadge();
    // Its own slot in the summary grid, one row under the number — and not in the badge row
    // below the summary, where it read as a property of the card rather than of the number.
    expect(badge.closest("[data-projection-badge]")).not.toBeNull();
    expect(toggleButton().contains(badge)).toBe(false);
    expect(badge.closest("[data-card-summary]")).not.toBeNull();
    // The number and its caption are still right there, in the column the badge is aligned to.
    const projection = container.querySelector("[data-projection]");
    expect(projection?.textContent).toContain("80.0");
    expect(projection?.textContent).toContain("proj");
  });

  it("explains the caveat on tap, naming the starters and the coverage", () => {
    renderCard(partialTeam());
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.click(partialBadge());
    expect(screen.getByRole("tooltip")).toHaveTextContent(COVERAGE_SENTENCE);
  });

  /**
   * A tap is a `pointerdown` and then a `click`. The open tooltip's dismissable layer closes on
   * the pointerdown, so a toggle written as `!open` reads a state that is already `false` by the
   * time the click lands and re-opens what the tap meant to dismiss. The badge latches what the
   * reader saw before the tap instead.
   */
  it("closes the tooltip on a second tap", async () => {
    renderCard(partialTeam());
    const badge = partialBadge();
    const tap = async () => {
      fireEvent.pointerDown(badge);
      fireEvent.click(badge);
      await settle();
    };

    await tap();
    expect(screen.getByRole("tooltip")).toHaveTextContent(COVERAGE_SENTENCE);

    await tap();
    expect(screen.queryByRole("tooltip")).toBeNull();

    // And a third tap opens it again: the latch is a toggle, not a one-way close.
    await tap();
    expect(screen.getByRole("tooltip")).toHaveTextContent(COVERAGE_SENTENCE);
  });

  it("opens on keyboard focus as well as on tap", () => {
    renderCard(partialTeam());
    const badge = partialBadge();
    badge.focus();
    expect(badge).toHaveFocus();
    fireEvent.focus(badge);
    expect(screen.getByRole("tooltip")).toHaveTextContent(COVERAGE_SENTENCE);
  });

  it("gives the sentence to a screen reader whether or not the tooltip is open", () => {
    renderCard(partialTeam());
    const describedBy = partialBadge().getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    const description = document.getElementById(describedBy as string);
    expect(description?.textContent).toBe(COVERAGE_SENTENCE);
  });

  it("keeps a 44px target and the shared focus ring on the badge", () => {
    renderCard(partialTeam());
    const className = partialBadge().className;
    expect(className).toContain("min-h-[44px]");
    expect(className).toContain("focus-visible:ring-2");
  });

  it("falls back to the plain label when the week has no starter counts", () => {
    renderCard({
      ...partialTeam(),
      startersProjected: null,
      starterSlots: null,
    });
    fireEvent.click(partialBadge());
    expect(screen.getByRole("tooltip")).toHaveTextContent(
      "Partial projection coverage",
    );
    expect(screen.queryByText(/starters have a projection/)).toBeNull();
  });

  it("puts no badge under a projection that clears the gate", () => {
    renderCard();
    expect(
      screen.queryByRole("button", { name: "Partial projection coverage" }),
    ).toBeNull();
  });
});
