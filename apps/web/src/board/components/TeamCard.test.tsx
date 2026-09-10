import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BoardTeam, RosterPlayer } from "../types";
import {
  CHIP_ROW_MIN_HEIGHT_CLASS,
  OWNER_NAME_RESERVE_ONE_CHIP_CLASS,
  OWNER_NAME_RESERVE_TWO_CHIP_CLASS,
  SUMMARY_MIN_HEIGHT_CLASS,
  TEAM_CARD_CLASS,
  TeamCard,
} from "./TeamCard";

/**
 * One turn of the macrotask queue. Radix registers the open tooltip's outside-pointerdown
 * listener from a `setTimeout(0)`, so a tap fired in the same tick as the open is not the tap a
 * reader makes — the layer that closes on pointerdown is not listening yet.
 */
const settle = () =>
  act(() => new Promise<void>((resolve) => setTimeout(resolve, 0)));

/** The chip's visible wording, spelled once. */
const PARTIAL_BADGE_TEXT = "partial";
const OUT_CHIP_TEXT = "1 starter out";

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
  injuryStatus: null,
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

/** The `partial` chip, beside the owner's name. */
const partialChip = () =>
  screen.getByText(PARTIAL_BADGE_TEXT).closest("[data-chip]");

/** The `N starter(s) out` chip, beside the owner's name. */
const outChip = () => screen.getByText(OUT_CHIP_TEXT).closest("[data-chip]");

/** The chip row overlaid on the owner's line, mounted whether or not it holds anything. */
const chipRow = (container: HTMLElement) =>
  container.querySelector("[data-chip-row]");

/** The row below the summary line the chips fall back to, likewise always mounted. */
const chipStack = (container: HTMLElement) =>
  container.querySelector("[data-chip-stack]");

/** The owner's name, which reserves room for whatever is overlaid on its line. */
const ownerName = (container: HTMLElement) =>
  container.querySelector("[data-owner-name]");

/** What is in a chip row, named by state rather than by wording. */
const chipKinds = (row: Element | null) =>
  [...(row?.querySelectorAll("[data-chip]") ?? [])].map((chip) =>
    chip.getAttribute("data-chip"),
  );

/** The summary's shape: its own tag and data attribute, and its children's, in order. */
const outline = (container: HTMLElement) => {
  const summary = container.querySelector("[data-card-summary]");
  return [...(summary?.children ?? [])].map((child) =>
    [
      child.tagName,
      child.hasAttribute("data-chip-row") ? "chip-row" : "",
      child.hasAttribute("data-chip-stack") ? "chip-stack" : "",
      child.getAttribute("aria-controls") === null ? "" : "toggle",
    ].join(":"),
  );
};

/** Every element between the card and its collapsible panel: the rows a card is made of. */
const rowCount = (container: HTMLElement) =>
  container.querySelectorAll(
    `.${TEAM_CARD_CLASS} > * > div:not([hidden]):not([data-chip-row])`,
  ).length;

/** The sentence a chip is described by, read the way a screen reader would reach it. */
const chipDescription = (chip: Element | null) => {
  const id = chip?.getAttribute("aria-describedby");
  return id === null || id === undefined
    ? null
    : document.getElementById(id)?.textContent;
};

/** A tap: `pointerdown`, then `click`, then the turn of the queue Radix waits for. */
const tap = async (element: Element) => {
  fireEvent.pointerDown(element);
  fireEvent.click(element);
  await settle();
};

/** A lineup with one out tight end and everyone else fit and projected — Ben's own card. */
const outTeam = (): Partial<BoardTeam> => {
  const roster = fullLineup();
  return {
    roster: roster.map((entry, index) =>
      index === 5
        ? player({
            ...entry,
            sleeperPlayerId: entry.sleeperPlayerId,
            fullName: "Broken Tightend",
            injuryStatus: "Out",
            projectedPoints: null,
          })
        : entry,
    ),
    startersProjected: LEAGUE_SLOTS.length - 1,
    starterSlots: LEAGUE_SLOTS.length,
    coveragePct: 88.9,
    isProvisional: true,
    emptySlots: 0,
  };
};

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
    name: "below the gate: the number stays, with a partial chip by the owner",
    team: {
      projectedPoints: 80,
      coveragePct: 66.67,
      isProvisional: true,
      startersProjected: 6,
      starterSlots: 9,
    },
    present: ["80.0", "partial"],
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

  it("puts a provisional ruling in a tooltip, not in the label", async () => {
    renderCard({
      isEliminated: true,
      eliminatedWeek: 4,
      eliminationSource: "sleeper_inferred",
    });
    const chip = screen.getByText("Eliminated week 4").closest("[data-chip]");
    // The label stays the plain ruling; the qualification is one tap away, like every other
    // chip on the line — a native `title` never opened on the phone this board is read on.
    expect(chip).not.toHaveAttribute("title");
    expect(chipDescription(chip)).toContain("Provisional");
    await tap(chip as Element);
    expect(screen.getByRole("tooltip")).toHaveTextContent(/Provisional/);
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
    const chip = screen.getByText("Eliminated week 4").closest("[data-chip]");
    expect(chip).not.toHaveAttribute("title");
    // Nothing to explain, so the chip is a plain span rather than a trigger for an empty
    // tooltip: an adjudicated elimination is simply the fact.
    expect(chip?.tagName).toBe("SPAN");
    expect(chipDescription(chip)).toBeNull();
    expect(screen.getByText("Patrick Mahomes")).toBeInTheDocument();
  });

  it("does not date a projection that was never computed", () => {
    renderCard({
      projectedPoints: null,
      coveragePct: null,
      isProvisional: true,
    });
    const chip = screen
      .getByText("Projection unavailable")
      .closest("[data-chip]");
    expect(chip).not.toHaveAttribute("title");
    expect(chipDescription(chip)).toBeNull();
    expect(screen.queryByText(/Computed /)).toBeNull();
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
 * Ben's addendum: an injured starter and a starter nobody has projected read identically on a
 * roster row, so the row carries Sleeper's own flag after the position.
 */
describe("TeamCard injury tags", () => {
  const injured = (status: string | null) => ({
    roster: [
      player({
        sleeperPlayerId: "4046",
        fullName: "Broken Tightend",
        position: "TE",
        nflTeam: "ATL",
        injuryStatus: status,
      }),
    ],
  });

  it("tags an out starter after the position, in the warning token", () => {
    renderCard(injured("Out"), { open: true });
    const row = screen.getByText("Broken Tightend").closest("li");
    expect(row?.textContent).toContain("TE · ATL");
    const tag = row?.querySelector("[data-injury]");
    expect(tag).not.toBeNull();
    expect(tag).toHaveAttribute("data-injury", "Out");
    expect(tag).toHaveAttribute("title", "Out");
    expect(tag?.className).toContain("text-destructive");
  });

  it("spells IR out in the tag's title, and Q and D in short", () => {
    renderCard(injured("IR"), { open: true });
    expect(screen.getByText("IR").closest("[data-injury]")).toHaveAttribute(
      "title",
      "Injured reserve",
    );
    // The full wording reaches a screen reader whether or not the title is hovered.
    expect(screen.getByText("Injured reserve").className).toContain("sr-only");
  });

  it.each([
    ["Questionable", "Q"],
    ["Doubtful", "D"],
  ])("marks a %s starter with %s, but not as a warning", (status, tag) => {
    renderCard(injured(status), { open: true });
    const element = screen.getByText(tag).closest("[data-injury]");
    expect(element).toHaveAttribute("title", status);
    expect(element?.className).not.toContain("text-destructive");
  });

  it("leaves a fit player untagged", () => {
    const { container } = renderCard(injured(null), { open: true });
    expect(container.querySelector("[data-injury]")).toBeNull();
  });
});

/**
 * Ben's addendum: "make every card the same height — the badge currently changes card height",
 * and "I'd prefer the badge by the owner's name." So the chips moved onto the owner's line, the
 * chip row is always mounted, and the summary carries a fixed height.
 */
describe("TeamCard summary chips", () => {
  it("puts the partial chip on the owner's line, outside the toggle", () => {
    const { container } = renderCard(partialTeam());
    const chip = partialChip();
    expect(chip).not.toBeNull();
    expect(chip).toHaveAttribute("data-chip", "partial");
    const row = chipRow(container);
    expect(row?.contains(chip as Node)).toBe(true);
    // On the owner's line: the row and the toggle share the summary grid's first cell.
    expect(row?.className).toContain("col-start-1");
    expect(row?.className).toContain("row-start-1");
    expect(row?.className).toContain("justify-self-end");
    expect(row?.parentElement).toBe(
      container.querySelector("[data-card-summary]"),
    );
    // And *not* inside the button, which is what lets a chip be a tooltip trigger at all.
    expect(toggleButton().contains(row as Node)).toBe(false);
    expect((row as Element).closest("button[aria-controls]")).toBeNull();
  });

  it("explains the partial chip on a tap, and to a screen reader without one", async () => {
    renderCard(partialTeam());
    const chip = partialChip();
    // The sentence reaches a screen reader whether or not the tooltip is open.
    expect(chipDescription(chip)).toBe(COVERAGE_SENTENCE);
    expect(screen.queryByRole("tooltip")).toBeNull();

    await tap(chip as Element);
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveTextContent(COVERAGE_SENTENCE);
    // Dated in words, never as an ISO string (see `derive/time`).
    expect(tooltip).toHaveTextContent(/Computed /);
    expect(tooltip.textContent ?? "").not.toMatch(/\d{4}-\d{2}-\d{2}T/);
  });

  it("opens the chip's tooltip on keyboard focus as well as on tap", () => {
    renderCard(partialTeam());
    const chip = partialChip() as HTMLElement;
    chip.focus();
    expect(chip).toHaveFocus();
    fireEvent.focus(chip);
    expect(screen.getByRole("tooltip")).toHaveTextContent(COVERAGE_SENTENCE);
  });

  it("closes the chip's tooltip on a second tap", async () => {
    renderCard(partialTeam());
    const chip = partialChip() as Element;
    await tap(chip);
    expect(screen.getByRole("tooltip")).toHaveTextContent(COVERAGE_SENTENCE);
    await tap(chip);
    expect(screen.queryByRole("tooltip")).toBeNull();
    await tap(chip);
    expect(screen.getByRole("tooltip")).toHaveTextContent(COVERAGE_SENTENCE);
  });

  it("keeps a 44px target and the shared focus ring on a chip that opens", () => {
    renderCard(partialTeam());
    const className = (partialChip() as Element).className;
    expect(className).toContain(CHIP_ROW_MIN_HEIGHT_CLASS);
    expect(className).toContain("focus-visible:ring-2");
  });

  /**
   * Availability may only *suppress* the data layer's caveat, never stand in for it. With no
   * starter counts there is no adjusted coverage to measure, so there is nothing to suppress
   * with and the caveat stands — under the plain label, because the two figures behind the
   * sentence are exactly what the week's row is missing.
   */
  it("keeps the chip, under the plain label, when the week has no starter counts", () => {
    renderCard({
      ...partialTeam(),
      startersProjected: null,
      starterSlots: null,
    });
    const chip = partialChip();
    expect(chip).not.toBeNull();
    expect(chipDescription(chip)).toBe("Partial projection coverage");
    expect(screen.queryByText(/starters have a projection/)).toBeNull();
  });

  it("keeps the chip on a two-thirds-covered card with nobody out", () => {
    // 6 of 9 is 66.7 percent, the lineup is full and fit, and no arithmetic explains it away.
    const roster = fullLineup();
    renderCard(
      {
        ...partialTeam(),
        roster: roster.map((entry, index) =>
          index < 3 ? player({ ...entry, projectedPoints: null }) : entry,
        ),
        emptySlots: 0,
      },
      { rosterPositions: LEAGUE_SLOTS },
    );
    expect(partialChip()).not.toBeNull();
    expect(chipDescription(partialChip())).toContain("(66.7%)");
    expect(screen.queryByText(/starters? out/)).toBeNull();
  });

  /**
   * A row can be provisional because the *league-wide* run was short rather than because this
   * team's own coverage is (`is_provisional` is `coverage_pct < 95 or run_coverage_pct < 95`).
   * No injury explains that, so a full-coverage provisional card keeps its chip.
   */
  it("keeps the chip on a provisional card whose own coverage is full", () => {
    renderCard(
      {
        coveragePct: 100,
        isProvisional: true,
        startersProjected: 9,
        starterSlots: 9,
        roster: fullLineup(),
        emptySlots: 0,
      },
      { rosterPositions: LEAGUE_SLOTS },
    );
    expect(partialChip()).not.toBeNull();
  });

  it("puts no chip on a card whose projection clears the gate", () => {
    const { container } = renderCard();
    expect(screen.queryByText(PARTIAL_BADGE_TEXT)).toBeNull();
    expect(container.querySelector("[data-chip]")).toBeNull();
  });

  it("keeps the chip row on one line so no chip can grow the card", () => {
    const { container } = renderCard(outTeam(), {
      rosterPositions: LEAGUE_SLOTS,
    });
    const row = chipRow(container);
    expect(row?.className).toContain("flex-nowrap");
    expect(row?.className).toContain("overflow-hidden");
    for (const chip of container.querySelectorAll("[data-chip]")) {
      expect(chip.className).toContain("whitespace-nowrap");
    }
  });

  // An empty row spans the end of the owner's line on every card; if it took pointer events it
  // would eat the taps that used to open the card there.
  it("leaves the row itself inert so it never swallows a tap on the card", () => {
    const onToggle = vi.fn();
    const { container } = renderCard({}, { onToggle });
    expect(chipRow(container)?.className).toContain("pointer-events-none");
    fireEvent.click(screen.getByText("benray"));
    expect(onToggle).toHaveBeenCalledWith(7);
  });

  // A control inside a <button> is invalid HTML, and it cost the card its whole-card tap
  // target the last time. The chips are siblings of the toggle, laid over its first row.
  it("nests no control inside the summary button", () => {
    renderCard(outTeam(), { rosterPositions: LEAGUE_SLOTS });
    expect(toggleButton().querySelector("button, a, input, select")).toBeNull();
  });
});

/**
 * Ben's addendum: "make every card the same height — the badge currently changes card height."
 * The chip row is mounted on every card with a floor of its own, and the badges that used to
 * sit in a row *below* the summary — the elimination ruling and `Projection unavailable` — are
 * chips in that same row, so no card carries a row its neighbour does not.
 */
describe("TeamCard equal heights", () => {
  const loud = () => ({
    ...outTeam(),
    isEliminated: true,
    eliminatedWeek: 4,
    eliminationSource: "sleeper_inferred" as const,
  });

  it("gives an eliminated card and a live one the same summary structure", () => {
    const eliminated = renderCard(loud(), { rosterPositions: LEAGUE_SLOTS });
    const eliminatedOutline = outline(eliminated.container);
    const eliminatedRows = rowCount(eliminated.container);
    // One visible row on the loudest card there is: the summary. A second one — the badge row
    // this replaced — is exactly the extra height Ben was looking at.
    expect(eliminatedRows).toBe(1);
    // The loud card really is loud: the elimination ruling is a chip in the row, not a row.
    expect(
      chipRow(eliminated.container)?.querySelectorAll("[data-chip]").length,
    ).toBeGreaterThan(1);
    expect(
      screen.getByText("Eliminated week 4").closest("[data-chip-row]"),
    ).not.toBeNull();
    eliminated.unmount();

    const live = renderCard({}, { rosterPositions: LEAGUE_SLOTS });
    expect(
      chipRow(live.container)?.querySelectorAll("[data-chip]"),
    ).toHaveLength(0);
    // Same boxes, in the same order, and the same number of rows in the card: the only
    // difference between the two cards is what is *inside* the chip row.
    expect(outline(live.container)).toEqual(eliminatedOutline);
    expect(rowCount(live.container)).toBe(eliminatedRows);
  });

  it("floors the summary and the chip row on every card, chips or not", () => {
    const eliminated = renderCard(loud(), { rosterPositions: LEAGUE_SLOTS });
    const summary = eliminated.container.querySelector("[data-card-summary]");
    expect(summary?.className).toContain(SUMMARY_MIN_HEIGHT_CLASS);
    expect(chipRow(eliminated.container)?.className).toContain(
      CHIP_ROW_MIN_HEIGHT_CLASS,
    );
    eliminated.unmount();

    const live = renderCard({}, { rosterPositions: LEAGUE_SLOTS });
    expect(
      live.container.querySelector("[data-card-summary]")?.className,
    ).toContain(SUMMARY_MIN_HEIGHT_CLASS);
    expect(chipRow(live.container)?.className).toContain(
      CHIP_ROW_MIN_HEIGHT_CLASS,
    );
  });
});

/**
 * Ben's report: "his TE is injured with a 0 projection, and his card says `partial` as if the
 * data were missing." An out starter is reported as out; only a shortfall he does not explain
 * is still `partial`.
 */
describe("TeamCard out starters", () => {
  const options = { rosterPositions: LEAGUE_SLOTS };

  it("says `1 starter out` instead of `partial` for Ben's card", () => {
    renderCard(outTeam(), options);
    const chip = outChip();
    expect(chip).toHaveAttribute("data-chip", "out");
    expect(chip?.className).toContain("text-destructive");
    expect(screen.queryByText(PARTIAL_BADGE_TEXT)).toBeNull();
  });

  it("names the out starters and their statuses on a tap", async () => {
    renderCard(outTeam(), options);
    // The names reach a screen reader without the tooltip being opened at all…
    expect(chipDescription(outChip())).toBe(
      "Out starters: Broken Tightend (Out)",
    );
    // …and a thumb, which a native `title` never gave them, opens the same sentence.
    await tap(outChip() as Element);
    expect(screen.getByRole("tooltip")).toHaveTextContent(
      "Out starters: Broken Tightend (Out)",
    );
  });

  it("still says `partial` when a fit starter is the one without a number", () => {
    const roster = fullLineup();
    renderCard(
      {
        roster: roster.map((entry, index) =>
          index === 3 ? player({ ...entry, projectedPoints: null }) : entry,
        ),
        startersProjected: LEAGUE_SLOTS.length - 1,
        starterSlots: LEAGUE_SLOTS.length,
        coveragePct: 88.9,
        isProvisional: true,
        emptySlots: 0,
      },
      options,
    );
    expect(screen.getByText(PARTIAL_BADGE_TEXT)).toBeInTheDocument();
    expect(screen.queryByText(/starters? out/)).toBeNull();
  });

  it("shows both chips, out first, when both are true", () => {
    const roster = fullLineup();
    const { container } = renderCard(
      {
        roster: roster.map((entry, index) =>
          index === 5
            ? player({
                ...entry,
                fullName: "Broken Tightend",
                injuryStatus: "Out",
                projectedPoints: null,
              })
            : index === 3
            ? player({ ...entry, projectedPoints: null })
            : entry,
        ),
        startersProjected: LEAGUE_SLOTS.length - 2,
        starterSlots: LEAGUE_SLOTS.length,
        coveragePct: 77.8,
        isProvisional: true,
        emptySlots: 0,
      },
      options,
    );
    expect(
      [...container.querySelectorAll("[data-chip]")].map((chip) =>
        chip.getAttribute("data-chip"),
      ),
    ).toEqual(["out", "partial"]);
  });

  it("leaves a questionable starter out of the count", () => {
    const roster = fullLineup();
    renderCard(
      {
        roster: roster.map((entry, index) =>
          index === 5
            ? player({ ...entry, injuryStatus: "Questionable" })
            : entry,
        ),
        emptySlots: 0,
      },
      options,
    );
    expect(screen.queryByText(/starters? out/)).toBeNull();
  });

  it("reports the out starter even when there is no projection row at all", () => {
    renderCard(
      {
        ...outTeam(),
        projectedPoints: null,
        coveragePct: null,
        startersProjected: null,
        starterSlots: null,
        emptySlots: null,
      },
      options,
    );
    expect(outChip()).not.toBeNull();
    expect(screen.getByText("Projection unavailable")).toBeInTheDocument();
  });
});

/**
 * Re-review of the fix round: `pr-24` on the owner's name was one chip's worth of room under a
 * row that now also carries the elimination ruling and `Projection unavailable`, so two chips
 * rendered over the name and a third clipped. The reserve follows the chips the card actually
 * has, and past two they leave the owner's line for a row of their own.
 */
describe("TeamCard chip crowding", () => {
  const options = { rosterPositions: LEAGUE_SLOTS };

  /** Ben's card, eliminated: an out starter and an elimination, on one line. */
  const twoChipTeam = (): Partial<BoardTeam> => ({
    ...outTeam(),
    isEliminated: true,
    eliminatedWeek: 4,
    eliminationSource: "adjudicator",
  });

  /** The same card with no projection row: everything this card can say at once. */
  const threeChipTeam = (): Partial<BoardTeam> => ({
    ...twoChipTeam(),
    projectedPoints: null,
  });

  it("keeps the one-chip reserve on a card carrying one chip", () => {
    const { container } = renderCard(partialTeam());
    expect(chipKinds(chipRow(container))).toEqual(["partial"]);
    expect(ownerName(container)?.className).toContain(
      OWNER_NAME_RESERVE_ONE_CHIP_CLASS,
    );
  });

  it("leaves the name its whole line when there is no chip at all", () => {
    const { container } = renderCard();
    expect(chipKinds(chipRow(container))).toEqual([]);
    // Not "a narrower reserve": none. There is nothing on the line to dodge.
    expect(ownerName(container)?.className).not.toContain("pr-");
  });

  it("widens the reserve for two chips instead of running them over the name", () => {
    const { container } = renderCard(twoChipTeam(), options);
    expect(chipKinds(chipRow(container))).toEqual(["out", "eliminated"]);
    const className = ownerName(container)?.className ?? "";
    expect(className).toContain(OWNER_NAME_RESERVE_TWO_CHIP_CLASS);
    expect(className).not.toContain(OWNER_NAME_RESERVE_ONE_CHIP_CLASS);
    // Still one row on the card: two chips stay on the owner's line, where Ben wants them.
    expect(rowCount(container)).toBe(1);
    expect(chipKinds(chipStack(container))).toEqual([]);
  });

  it("moves three chips off the owner's line into the row below the summary", () => {
    const { container } = renderCard(threeChipTeam(), options);
    expect(chipKinds(chipRow(container))).toEqual([]);
    expect(chipKinds(chipStack(container))).toEqual([
      "out",
      "unavailable",
      "eliminated",
    ]);
    // Nothing is overlaid on the name any more, so it reserves nothing.
    expect(ownerName(container)?.className).not.toContain("pr-");
  });

  it("keeps a stacked chip a real tooltip trigger, in an inert row", async () => {
    const { container } = renderCard(threeChipTeam(), options);
    const row = chipStack(container);
    expect(row?.className).toContain("pointer-events-none");
    const chip = outChip() as HTMLElement;
    expect(row?.contains(chip)).toBe(true);
    expect(chip.tagName).toBe("BUTTON");
    expect(chip.className).toContain("pointer-events-auto");
    await tap(chip);
    expect(screen.getByRole("tooltip")).toHaveTextContent(
      "Out starters: Broken Tightend (Out)",
    );
  });

  it("keeps the three-chip card the same shape and height as a plain one", () => {
    const stacked = renderCard(threeChipTeam(), options);
    const stackedOutline = outline(stacked.container);
    const stackedRows = rowCount(stacked.container);
    expect(chipStack(stacked.container)?.className).toContain(
      CHIP_ROW_MIN_HEIGHT_CLASS,
    );
    stacked.unmount();

    // The row is mounted, floored and empty on the card with nothing to say — which is what
    // stops the loud card being the one card in the grid that is taller than its neighbours.
    const plain = renderCard({}, options);
    expect(chipStack(plain.container)?.className).toContain(
      CHIP_ROW_MIN_HEIGHT_CLASS,
    );
    expect(chipKinds(chipStack(plain.container))).toEqual([]);
    expect(outline(plain.container)).toEqual(stackedOutline);
    expect(rowCount(plain.container)).toBe(stackedRows);
  });
});
