import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BoardTeam, RosterPlayer } from "../types";
import { TEAM_CARD_CLASS, TeamCard } from "./TeamCard";

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

/** The chip row, mounted whether or not there is anything in it. */
const chipRow = (container: HTMLElement) =>
  container.querySelector("[data-chip-row]");

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
  it("puts the partial chip on the owner's line, inside the toggle", () => {
    const { container } = renderCard(partialTeam());
    const chip = partialChip();
    expect(chip).not.toBeNull();
    expect(chip).toHaveAttribute("data-chip", "partial");
    expect(chipRow(container)?.contains(chip as Node)).toBe(true);
    // The owner's name is in the same line box as the chip row.
    expect(screen.getByText("benray").parentElement).toBe(
      chipRow(container)?.parentElement,
    );
    // And the whole line is still inside the one toggle, so the card taps as one thing.
    expect(toggleButton().contains(chip as Node)).toBe(true);
  });

  it("explains the partial chip in its title and to a screen reader", () => {
    renderCard(partialTeam());
    const chip = partialChip();
    expect(chip?.getAttribute("title")).toContain(COVERAGE_SENTENCE);
    // Dated in words, never as an ISO string (see `derive/time`).
    expect(chip?.getAttribute("title")).toMatch(/Computed /);
    expect(chip?.getAttribute("title") ?? "").not.toMatch(/\d{4}-\d{2}-\d{2}T/);
    const spoken = chip?.querySelector(".sr-only");
    expect(spoken?.textContent).toContain("Partial projection coverage");
    expect(spoken?.textContent).toContain(COVERAGE_SENTENCE);
  });

  it("falls back to the plain label when the week has no starter counts", () => {
    renderCard({
      ...partialTeam(),
      startersProjected: null,
      starterSlots: null,
    });
    // No counts means no adjusted coverage to measure, so there is no partial claim at all.
    expect(screen.queryByText(PARTIAL_BADGE_TEXT)).toBeNull();
  });

  it("puts no chip on a card whose projection clears the gate", () => {
    const { container } = renderCard();
    expect(screen.queryByText(PARTIAL_BADGE_TEXT)).toBeNull();
    expect(container.querySelector("[data-chip]")).toBeNull();
  });

  /**
   * The height fix. The chip row is a real element on every card, chips or not, so the summary
   * has one structure rather than two — an element that appears and disappears is what was
   * changing the card's height in the first place.
   */
  it("renders the same summary structure with and without chips", () => {
    const withChips = renderCard(outTeam(), {
      rosterPositions: LEAGUE_SLOTS,
    });
    const chipRowWith = chipRow(withChips.container);
    expect(chipRowWith).not.toBeNull();
    expect(chipRowWith?.querySelectorAll("[data-chip]").length).toBeGreaterThan(
      0,
    );
    const summaryWith = withChips.container.querySelector(
      "[data-card-summary]",
    );
    withChips.unmount();

    const without = renderCard({}, { rosterPositions: LEAGUE_SLOTS });
    const chipRowWithout = chipRow(without.container);
    expect(chipRowWithout).not.toBeNull();
    expect(chipRowWithout?.querySelectorAll("[data-chip]")).toHaveLength(0);
    const summaryWithout = without.container.querySelector(
      "[data-card-summary]",
    );

    // The same box, with the same fixed height, in both branches.
    expect(summaryWith?.className).toBe(summaryWithout?.className);
    expect(summaryWithout?.className).toContain("min-h-");
    expect(chipRowWith?.className).toBe(chipRowWithout?.className);
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

  // A control inside a <button> is invalid HTML. The chips are spans precisely so they can
  // live on the owner's line without splitting the summary's tap target again.
  it("nests no control inside the summary button", () => {
    renderCard(outTeam(), { rosterPositions: LEAGUE_SLOTS });
    expect(toggleButton().querySelector("button, a, input, select")).toBeNull();
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

  it("names the out starters and their statuses in the chip's tooltip", () => {
    renderCard(outTeam(), options);
    expect(outChip()).toHaveAttribute(
      "title",
      "Out starters: Broken Tightend (Out)",
    );
    expect(outChip()?.querySelector(".sr-only")?.textContent).toContain(
      "Broken Tightend (Out)",
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
