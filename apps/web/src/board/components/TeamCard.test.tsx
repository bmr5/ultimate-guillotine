import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BoardTeam, RosterPlayer } from "../types";
import {
  CHIP_ROW_HEIGHT_CLASS,
  CHIP_ROW_INDENT_CLASS,
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

/** The `partial` chip, on the line under the owner's name. */
const partialChip = () =>
  screen.getByText(PARTIAL_BADGE_TEXT).closest("[data-chip]");

/** The `N starter(s) out` chip, on the line under the owner's name. */
const outChip = () => screen.getByText(OUT_CHIP_TEXT).closest("[data-chip]");

/** The chip line under the owner's name, mounted whether or not it holds anything. */
const chipRow = (container: HTMLElement) =>
  container.querySelector("[data-chip-row]");

/** The owner's name, which keeps its whole line now that nothing is overlaid on it. */
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
      child.getAttribute("aria-controls") === null ? "" : "toggle",
    ].join(":"),
  );
};

/**
 * The shape every card's summary has to have, written out rather than read off a second render:
 * the toggle, the chip line under it, and the chevron's redundant target. Spelling it makes the
 * equal-height cases assert something — comparing two renders only proved the component is
 * deterministic. A card that mounts its chip line only when it has chips fails here first.
 */
const PLAIN_OUTLINE = ["BUTTON::toggle", "DIV:chip-row:", "BUTTON::"];

/**
 * The summary grid's rows, read off the row each child is placed in: the toggle's line, the
 * chevron beside it, and the chip line below. Two on every card — the chip line is mounted
 * whether or not it has anything to say, which is what makes the equal height structural rather
 * than a coincidence of what each card carries.
 */
const rowCount = (container: HTMLElement) => {
  const summary = container.querySelector("[data-card-summary]");
  return new Set(
    [...(summary?.children ?? [])].flatMap((child) =>
      [...child.classList].filter((name) => name.startsWith("row-start-")),
    ),
  ).size;
};

/** The card's own boxes between it and the collapsible panel — the summary, and nothing else. */
const cardRowCount = (container: HTMLElement) =>
  container.querySelectorAll(`.${TEAM_CARD_CLASS} > * > div:not([hidden])`)
    .length;

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

/**
 * The only two-chip card the rule allows: one out starter *and* a fit starter with no number,
 * so the out chip explains part of the shortfall and `partial` survives for the rest.
 */
const outAndPartialTeam = (): Partial<BoardTeam> => {
  const roster = fullLineup();
  return {
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
 * and "I'd prefer the badge by the owner's name." So the chips sit on their own line directly
 * under the name, indented to it, always mounted, under a summary with a fixed floor.
 */
describe("TeamCard summary chips", () => {
  it("puts the partial chip under the owner's name, outside the toggle", () => {
    const { container } = renderCard(partialTeam());
    const chip = partialChip();
    expect(chip).not.toBeNull();
    expect(chip).toHaveAttribute("data-chip", "partial");
    const row = chipRow(container);
    expect(row?.contains(chip as Node)).toBe(true);
    // The summary grid's second row, in the same column as the toggle, indented past the rank
    // to the name's own left edge and left-aligned under it.
    expect(row?.className).toContain("col-start-1");
    expect(row?.className).toContain("row-start-2");
    expect(row?.className).toContain(CHIP_ROW_INDENT_CLASS);
    expect(row?.className).not.toContain("justify-self-end");
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

  it("keeps the chip to the line's own height, with a ring the line cannot clip", () => {
    renderCard(partialTeam());
    const className = (partialChip() as Element).className;
    // 24px, the height of the line it sits on. The 44px target the overlaid row carried was
    // there so a chip could be dodged; on a line of its own it covers nothing.
    expect(className).toContain(CHIP_ROW_HEIGHT_CLASS);
    expect(className).toContain("focus-visible:ring-2");
    // And drawn inside the chip: the chip fills an `h-6 overflow-hidden` line, so a ring set
    // outside the chip's box — any `ring-offset`, including the `ring-offset-background` that
    // colours it — is drawn outside the line and clipped away by it.
    expect(className).toContain("focus-visible:ring-inset");
    expect(className).not.toContain("ring-offset");
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

  it("keeps the chip line to one line so no chip can grow the card", () => {
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

  // The chip line is mounted on every card, empty or not. It sits under the owner's line
  // rather than over it, so an empty one has nothing in it and covers nothing: the name is a
  // tap on the card, and no `pointer-events-none` is needed to keep it one.
  it("leaves an empty chip line with nothing in it to swallow a tap", () => {
    const onToggle = vi.fn();
    const { container } = renderCard({}, { onToggle });
    const row = chipRow(container);
    expect(row).not.toBeNull();
    expect(row?.children).toHaveLength(0);
    expect(row?.className).not.toContain("pointer-events-none");
    fireEvent.click(screen.getByText("benray"));
    expect(onToggle).toHaveBeenCalledWith(7);
  });

  // A control inside a <button> is invalid HTML, and it cost the card its whole-card tap
  // target the last time. The chips are siblings of the toggle, on the grid's second row.
  it("nests no control inside the summary button", () => {
    renderCard(outTeam(), { rosterPositions: LEAGUE_SLOTS });
    expect(toggleButton().querySelector("button, a, input, select")).toBeNull();
  });
});

/**
 * Ben's addendum: "make every card the same height — the badge currently changes card height."
 * The chip line is mounted on every card at a fixed height, and the badges that used to sit in a
 * row *below* the summary — the elimination ruling and `Projection unavailable` — are chips on
 * that line, so no card carries a box its neighbour does not.
 *
 * The ruling after round 3 moved that line off the owner's name and under it: two grid rows on
 * every card, 0 chips or 2, rather than an overlay a 375px name field cannot dodge.
 */
describe("TeamCard equal heights", () => {
  /** A card at each size the chip set can be: none, one chip, and the two-chip maximum. */
  const SIZES: { name: string; team: Partial<BoardTeam>; chips: number }[] = [
    { name: "no chips", team: {}, chips: 0 },
    {
      name: "one chip",
      team: {
        ...outTeam(),
        isEliminated: true,
        eliminatedWeek: 4,
        eliminationSource: "sleeper_inferred",
      },
      chips: 1,
    },
    { name: "two chips", team: outAndPartialTeam(), chips: 2 },
  ];

  it.each(SIZES)(
    "keeps a card with $name to the same two rows, in the same boxes",
    ({ team: overrides, chips }) => {
      const { container, unmount } = renderCard(overrides, {
        rosterPositions: LEAGUE_SLOTS,
      });
      // The case really is the size it claims: otherwise this is three copies of one card.
      expect(chipKinds(chipRow(container))).toHaveLength(chips);
      // Two grid rows on every card — the toggle's line and the chip line under it — whether
      // the chip line has two chips in it or none.
      expect(rowCount(container)).toBe(2);
      // And one box on the card itself: the summary. A second — the badge row this replaced,
      // and the stacked row that replaced *that* — is the extra height Ben was looking at.
      expect(cardRowCount(container)).toBe(1);
      expect(outline(container)).toEqual(PLAIN_OUTLINE);
      unmount();
    },
  );

  it("puts the loudest chip on the chip line rather than in a row of its own", () => {
    renderCard(
      {
        ...outTeam(),
        isEliminated: true,
        eliminatedWeek: 4,
        eliminationSource: "sleeper_inferred",
      },
      { rosterPositions: LEAGUE_SLOTS },
    );
    expect(
      screen.getByText("Eliminated week 4").closest("[data-chip-row]"),
    ).not.toBeNull();
  });

  it("floors the summary and fixes the chip line on every card, chips or not", () => {
    const loud = renderCard(outAndPartialTeam(), {
      rosterPositions: LEAGUE_SLOTS,
    });
    const summary = loud.container.querySelector("[data-card-summary]");
    expect(summary?.className).toContain(SUMMARY_MIN_HEIGHT_CLASS);
    expect(chipRow(loud.container)?.className).toContain(CHIP_ROW_HEIGHT_CLASS);
    loud.unmount();

    const live = renderCard({}, { rosterPositions: LEAGUE_SLOTS });
    expect(
      live.container.querySelector("[data-card-summary]")?.className,
    ).toContain(SUMMARY_MIN_HEIGHT_CLASS);
    // Fixed, not floored: an empty line has to hold the same band as a full one.
    expect(chipRow(live.container)?.className).toContain(CHIP_ROW_HEIGHT_CLASS);
    expect(chipRow(live.container)?.className).not.toContain("min-h-");
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
    const { container } = renderCard(outAndPartialTeam(), options);
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

  /**
   * The ruling after fix round 2: a card with no projection says only that. `2 starters out`
   * beside an em dash implies a number that was adjusted for them, and there is no number.
   */
  it("says only `Projection unavailable` when there is no projection row at all", () => {
    const { container } = renderCard(
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
    expect(chipKinds(chipRow(container))).toEqual(["unavailable"]);
    expect(screen.queryByText(/starters? out/)).toBeNull();
    expect(screen.getByText("Projection unavailable")).toBeInTheDocument();
    // The status is not lost — it is tagged on the player's own row when the card is expanded.
    expect(screen.queryByText("Broken Tightend")).toBeNull();
  });
});

/**
 * The ruling after fix round 3: no reserve fits. Measured on a 375px phone, the card is 343px
 * and the owner's name field 141px, against a two-chip set of 138.7px — so a two-chip card
 * showed no name at all, and a lone `Projection unavailable` (131.8px) overlapped the name it
 * sat beside. The chips have their own line under the name now, and the name has its whole
 * column back.
 */
describe("TeamCard chip crowding", () => {
  const options = { rosterPositions: LEAGUE_SLOTS };

  it("leaves the name its whole line with one chip on the card", () => {
    const { container } = renderCard(partialTeam());
    expect(chipKinds(chipRow(container))).toEqual(["partial"]);
    // No reserve at any chip count: nothing is overlaid on this line any more.
    expect(ownerName(container)?.className).not.toContain("pr-");
  });

  it("leaves the name its whole line when there is no chip at all", () => {
    const { container } = renderCard();
    expect(chipKinds(chipRow(container))).toEqual([]);
    expect(ownerName(container)?.className).not.toContain("pr-");
  });

  it("puts two chips on their own line rather than over the name", () => {
    const { container } = renderCard(outAndPartialTeam(), options);
    expect(chipKinds(chipRow(container))).toEqual(["out", "partial"]);
    expect(ownerName(container)?.className).not.toContain("pr-");
    const row = chipRow(container);
    // The line is row 2 of the summary grid, indented to the name's left edge, and stays one
    // line whatever it holds.
    expect(row?.className).toContain("row-start-2");
    expect(row?.className).toContain(CHIP_ROW_INDENT_CLASS);
    expect(row?.className).toContain("flex-nowrap");
    expect(rowCount(container)).toBe(2);
    expect(cardRowCount(container)).toBe(1);
  });

  /**
   * The line is only one line if nothing can exceed the pair it was measured for. This is the
   * card that used to carry three chips: eliminated, an out starter, and no projection at all.
   */
  it("says one thing on the card that used to say three", () => {
    const { container } = renderCard(
      {
        ...outTeam(),
        isEliminated: true,
        eliminatedWeek: 4,
        eliminationSource: "adjudicator",
        projectedPoints: null,
        coveragePct: null,
      },
      options,
    );
    expect(chipKinds(chipRow(container))).toEqual(["eliminated"]);
    expect(screen.queryByText(/starters? out/)).toBeNull();
    expect(screen.queryByText("Projection unavailable")).toBeNull();
    expect(screen.queryByText(PARTIAL_BADGE_TEXT)).toBeNull();
  });

  it("keeps every chip a real tooltip trigger on a line that covers nothing", async () => {
    const { container } = renderCard(outAndPartialTeam(), options);
    const row = chipRow(container);
    // The line is inert by having no children, not by `pointer-events-none`, so a chip does not
    // have to take its own events back to stay clickable.
    expect(row?.className).not.toContain("pointer-events-none");
    const chip = outChip() as HTMLElement;
    expect(row?.contains(chip)).toBe(true);
    expect(chip.tagName).toBe("BUTTON");
    expect(chip.className).not.toContain("pointer-events-auto");
    await tap(chip);
    expect(screen.getByRole("tooltip")).toHaveTextContent(
      "Out starters: Broken Tightend (Out)",
    );
  });
});
