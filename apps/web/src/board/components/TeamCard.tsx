import { memo, useId, useMemo, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import { resolveStarterAvailability } from "../derive/availability";
import {
  COVERAGE_GATE_PCT,
  partialCoverageExplanation,
  resolveProjectionDisplay,
} from "../derive/projection";
import { layoutStarters, resolveEmptySlotCount } from "../derive/roster";
import { formatComputedTitle } from "../derive/time";
import type { BoardTeam } from "../types";
import { RosterPanel } from "./RosterPanel";

/**
 * The class the scoped reduced-motion rule in `globals.css` hangs off. The rule is scoped to the
 * card rather than every `[data-state]` element on the page, so it cannot silently kill the
 * animation of an unrelated Radix component.
 */
export const TEAM_CARD_CLASS = "board-team-card";

/** Decimals the season total is shown with. */
const TOTAL_POINTS_DECIMALS = 1;

/**
 * Ben's card change 1: the card line leads with the season total rather than a win-loss record.
 * The visible word is the short one; the accessible label says which total it is, because
 * "Total 301.5" read out on its own could be a total of anything.
 */
const TOTAL_POINTS_TEXT = "Total";
const TOTAL_POINTS_LABEL = "Total points";

/** Shown in place of the FAAB figure when the team has no `team_season_state` row. */
const FAAB_UNKNOWN_TEXT = "FAAB —";

/**
 * The focus ring the header's toggles, buttons and search box all carry (see
 * `toggle-variants` / `button-variants`). This card's summary is a bare `<button>` rather than a
 * `Button`, so it has to name the ring itself or it is the one keyboard stop on the page with
 * no visible focus at all.
 */
const FOCUS_RING_CLASS =
  "ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

/** The short, visible form of the below-gate caveat; the full label rides along for readers. */
const PARTIAL_BADGE_TEXT = "partial";

/**
 * The collapsed summary's height, so every card in the grid is the same one.
 *
 * Ben's addendum: "make every card the same height — the badge currently changes card height."
 * A `min-h` alone would not do it; it works because everything inside the summary is bounded.
 * The owner line, the team name and the total line each truncate to one line, neither chip row
 * wraps, and the projection block is at most three lines (number, `proj`, empty count).
 * 6.5rem clears that tallest case with the card's `p-4` around it, so a card with chips, a card
 * with an empty-slot count and a plain card all measure the same.
 *
 * The summary's second grid row — the stacked chip row — sits under that floor and is mounted,
 * at its own fixed height, on every card. It is a band every card carries, not a row a loud
 * card grows.
 */
export const SUMMARY_MIN_HEIGHT_CLASS = "min-h-[6.5rem]";

/**
 * The floor under both chip rows — the overlay on the owner's line and the stacked row below
 * the summary — so each occupies the same band on every card whether it holds chips or none.
 * It is the 44px touch target the tooltip triggers inside them need anyway; naming it here is
 * what makes the equal-height claim independent of what is in either row.
 */
export const CHIP_ROW_MIN_HEIGHT_CLASS = "min-h-[44px]";

/**
 * The projection block's width. Fixed, for two reasons: the numbers line up down the grid, and
 * the chip row can reserve exactly this much room to its right (plus the toggle's `gap-3`) and
 * so never land on top of the number it is a footnote to.
 */
const PROJECTION_WIDTH_CLASS = "w-[4.5rem]";

/** `PROJECTION_WIDTH_CLASS` + the toggle's `gap-3`, kept next to it so the two cannot drift. */
const CHIP_ROW_RESERVE_CLASS = "pr-[5.25rem]";

/**
 * The room the owner's name leaves for the chips overlaid at the end of its line, indexed by
 * how many chips are actually on that line.
 *
 * It was one constant, on the argument that a name truncating to a different width depending on
 * whether its team had an injury is its own kind of jitter. That held while the row could only
 * hold one chip. It cannot: the elimination ruling and `Projection unavailable` moved into this
 * row, and `pr-24` is one chip's worth of room — two chips ran straight over the name they were
 * meant to sit beside, which is worse jitter than a name cut to two widths.
 *
 * One chip is the reserve as it was. Two is `2 starters out` (102px) and `Eliminated week 18`
 * (144px) plus the row's `gap-1` — 250px, measured in the browser at the card's own 11px
 * `Inter var`, not estimated. On a card narrower than about 26rem that reserve is the whole
 * name field and the name gives up its line rather than be written over; on a wide one it
 * keeps a readable stub. Three chips fit behind no reserve at all, so they leave the line
 * entirely — see `CHIP_STACK_THRESHOLD`.
 */
export const OWNER_NAME_RESERVE_ONE_CHIP_CLASS = "pr-24";
export const OWNER_NAME_RESERVE_TWO_CHIP_CLASS = "pr-[15.75rem]";

/** The reserve by chip count, so the name is padded for the chips the card actually has. */
const OWNER_NAME_RESERVE_CLASSES = [
  "",
  OWNER_NAME_RESERVE_ONE_CHIP_CLASS,
  OWNER_NAME_RESERVE_TWO_CHIP_CLASS,
] as const;

/**
 * The chip count from which the row stops being an overlay on the owner's name and becomes a
 * row of its own below the summary line. Three chips — an out starter, a caveat on the number
 * and an elimination — are the most the card can carry at once.
 */
const CHIP_STACK_THRESHOLD = OWNER_NAME_RESERVE_CLASSES.length;

/** Label for a team eliminated in a week the data layer does not know yet. */
const ELIMINATED_LABEL = "Eliminated";

/** The tooltip a Sleeper-inferred elimination carries; the label itself stays plain. */
const PROVISIONAL_ELIMINATION_TITLE =
  "Provisional: inferred from Sleeper, not yet ruled by the Adjudicator";

/** Said once above a frozen roster, so the reader knows why it never changes again. */
export const FROZEN_ROSTER_LABEL = "Final roster, frozen at elimination";

/** What the empty-slot count is called for a reader who cannot see it sitting under `proj`. */
const EMPTY_SLOTS_DESCRIPTION = "empty starter slots";

/** The visible pill: one line, its own border, small enough to sit on the owner's line. */
const CHIP_FACE_CLASS =
  "rounded-md border px-1.5 py-0.5 text-[0.6875rem] font-medium leading-4";

/** `destructive` for something costing points now; `muted` for a footnote on the number. */
type ChipTone = "destructive" | "muted";

const CHIP_TEXT_CLASS: Record<ChipTone, string> = {
  destructive: "text-destructive",
  muted: "text-muted-foreground",
};

const CHIP_BORDER_CLASS: Record<ChipTone, string> = {
  destructive: "border-destructive/40",
  muted: "border-border",
};

interface SummaryChipProps {
  /** The `data-chip` handle, so a test names the state rather than the styling. */
  kind: "out" | "partial" | "unavailable" | "eliminated";
  /** The short, visible wording. */
  text: string;
  /** The same thing spelled out for a screen reader, whether or not the tooltip is open. */
  label: string;
  /**
   * The sentence behind the chip. With one, the chip is a tooltip trigger; without one there is
   * nothing to open and the chip is a plain span.
   */
  description?: string | undefined;
  /** When the projection was computed, already in words. A second line under the sentence. */
  computedText?: string | undefined;
  tone: ChipTone;
}

/**
 * One chip on the owner's line.
 *
 * Ben asked for the badge "by the owner's name". The chips are therefore a *sibling* of the
 * summary toggle, laid over the end of the owner's line by the summary grid rather than nested
 * inside the button — a control inside a `<button>` is invalid HTML, and it was what cost the
 * card its whole-card tap target the last time. Outside it, a chip can be a real Radix tooltip
 * trigger, which is the point: the native `title` this replaced never opened on a tap, and a
 * phone is where this board is read.
 *
 * The tooltip is controlled rather than left to Radix's hover-and-focus default, because Radix
 * suppresses tooltips opened by touch. Hover and keyboard focus still open it through
 * `onOpenChange`; the click handler adds tap. The sentence is also mounted as visually hidden
 * text and named by `aria-describedby`, so a screen reader gets it whether or not the tooltip
 * is open.
 *
 * The tap toggle reads a latched copy of `open` rather than the current state, because by the
 * time `onClick` runs the state is no longer the one the reader tapped: the open tooltip's
 * dismissable layer closes on the `pointerdown` that starts the second tap, and Radix's own
 * trigger closes again on the click. A plain `!open` therefore resolves against a just-set
 * `false` and re-opens the tooltip the tap was meant to dismiss. `onPointerDownCapture` runs
 * before either close — capture, at the trigger, beats a document-level listener — so it records
 * what the reader actually saw, and the click toggles against that.
 */
const SummaryChip = memo(function SummaryChip({
  kind,
  text,
  label,
  description,
  computedText,
  tone,
}: SummaryChipProps) {
  const [open, setOpen] = useState(false);
  // What the tooltip was doing when the tap began. False is the right resting value: a click with
  // no pointerdown before it is a keyboard activation, and focus has already opened the tooltip.
  const openAtPointerDown = useRef(false);
  const descriptionId = useId();

  // A chip whose label is its own wording says it once: two copies of `Eliminated week 4`, one
  // hidden from sight and one from assistive technology, is a duplicate for anybody reading with
  // both. Only the short forms — `partial`, which is not a sentence a reader can act on — carry
  // a spoken label of their own.
  const face =
    label === text ? (
      <span className={cn(CHIP_FACE_CLASS, CHIP_BORDER_CLASS[tone])}>
        {text}
      </span>
    ) : (
      <>
        <span
          aria-hidden="true"
          className={cn(CHIP_FACE_CLASS, CHIP_BORDER_CLASS[tone])}
        >
          {text}
        </span>
        <span className="sr-only">{label}</span>
      </>
    );

  if (description === undefined) {
    return (
      <span
        data-chip={kind}
        className={cn(
          "inline-flex shrink-0 items-center whitespace-nowrap",
          CHIP_TEXT_CLASS[tone],
        )}
      >
        {face}
      </span>
    );
  }

  return (
    <TooltipProvider>
      <Tooltip open={open} onOpenChange={setOpen}>
        <TooltipTrigger asChild>
          <button
            type="button"
            data-chip={kind}
            aria-describedby={descriptionId}
            onPointerDownCapture={() => {
              openAtPointerDown.current = open;
            }}
            onClick={() => {
              const wasOpen = openAtPointerDown.current;
              openAtPointerDown.current = false;
              setOpen(!wasOpen);
            }}
            className={cn(
              // The row itself is inert so an empty one never swallows a tap meant for the
              // card; each chip takes its own events back, with a full-height touch target.
              "pointer-events-auto inline-flex shrink-0 items-center whitespace-nowrap rounded-md",
              CHIP_ROW_MIN_HEIGHT_CLASS,
              CHIP_TEXT_CLASS[tone],
              FOCUS_RING_CLASS,
            )}
          >
            {face}
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-[16rem] whitespace-pre-line text-left">
          <span className="block">{description}</span>
          {computedText === undefined ? null : (
            <span className="mt-1 block text-xs text-muted-foreground">
              {computedText}
            </span>
          )}
        </TooltipContent>
      </Tooltip>
      <span id={descriptionId} className="sr-only">
        {description}
      </span>
    </TooltipProvider>
  );
});

interface TeamCardProps {
  team: BoardTeam;
  rank: number;
  isOpen: boolean;
  onToggle: (teamId: number) => void;
  highlightedPlayerIds: ReadonlySet<string>;
  /** The league's lineup — `seasons.roster_positions` — which the empty slots are counted against. */
  rosterPositions: string[];
}

/**
 * One team's row on the board: the summary line, its chips, and the roster panel the summary
 * expands into. Open state is owned by the caller so only one card need be open at a time and
 * so the board can restore it from the URL.
 *
 * Ben's decision 3: an eliminated team is dimmed and sorted last but stays expandable, because
 * the frozen roster is the interesting part of an elimination.
 */
export const TeamCard = memo(function TeamCard({
  team,
  rank,
  isOpen,
  onToggle,
  highlightedPlayerIds,
  rosterPositions,
}: TeamCardProps) {
  const panelId = useId();
  // Laid out once per card rather than once per open card: the count below the projection and
  // the out-starter chip are both on the collapsed card, which is the point — Ben should not
  // have to expand nine cards to find the one missing a flex or starting an injured tight end.
  const starterRows = useMemo(
    () => layoutStarters(rosterPositions, team.roster),
    [rosterPositions, team.roster],
  );
  const emptySlots = resolveEmptySlotCount(team.emptySlots, starterRows);
  const projection = resolveProjectionDisplay(team);
  const totalPoints = team.pointsFor.toFixed(TOTAL_POINTS_DECIMALS);
  const faab =
    team.faabRemaining === null
      ? FAAB_UNKNOWN_TEXT
      : `${team.faabRemaining} FAAB`;

  // Ben's addendum: an out starter is reported as out, not counted as missing data. This is
  // what decides both chips — the out one from the roster, the partial one from what coverage
  // is left once the out starters and the empty slots leave the denominator.
  const availability = resolveStarterAvailability({
    starterRows,
    startersProjected: team.startersProjected,
    starterSlots: team.starterSlots,
    emptySlots,
  });
  // The data layer decides that the week is caveated; availability may only *suppress* that
  // verdict, never stand in for it. Requiring both to agree deleted the caveat from cards
  // availability had nothing to say about: a week with no starter counts at all (no adjusted
  // figure to measure), and a row flagged provisional for a reason that has nothing to do with
  // this lineup, both came back `isPartial: false` for want of an opinion rather than because
  // the projection was sound.
  //
  // `is_provisional` is `coverage_pct < 95 or run_coverage_pct < 95` (see
  // `sleeper/team_projections.py`), so the flag alone cannot veto the suppression: a team whose
  // own coverage is short is exactly the card Ben was looking at, and an out starter is the
  // explanation. It is the *second* limb — a row flagged provisional while its own coverage
  // clears the gate, because the league-wide run was short — that no injury can explain, and
  // that keeps its chip.
  const provisionalBeyondCoverage =
    team.isProvisional &&
    (team.coveragePct === null || team.coveragePct >= COVERAGE_GATE_PCT);
  const suppressed =
    availability.adjustedCoveragePct !== null &&
    !availability.isPartial &&
    !provisionalBeyondCoverage;
  const isPartial = projection.caveat === "partial" && !suppressed;

  // Only the partial chip carries a computed-at line: it is the one caveat where the age of
  // the number is the follow-up question. `Projection unavailable` means there is no number to
  // have been computed, so a "computed at" time on it would be a lie about a row that is absent.
  // A raw ISO timestamp is never surfaced (see `derive/time`), so it is formatted in the
  // viewer's own locale and timezone like every other time on the board.
  const computedText =
    isPartial && team.projectionComputedAt !== null
      ? formatComputedTitle(Date.parse(team.projectionComputedAt))
      : undefined;
  const coverageExplanation = partialCoverageExplanation(team);
  // The sentence behind the `partial` chip: the two figures the caveat is about, or the plain
  // label when the week's row does not carry them.
  const partialDescription =
    coverageExplanation ?? projection.caveatLabel ?? undefined;
  const eliminatedText =
    team.eliminatedWeek === null
      ? ELIMINATED_LABEL
      : `${ELIMINATED_LABEL} week ${team.eliminatedWeek}`;

  // Everything qualifying this card, in reading order, decided once. The row renders this list
  // and the owner's name reserves room against its length: two answers to "what is on this
  // line?" is how the name came to be padded for one chip while wearing two.
  const chips: SummaryChipProps[] = [];
  if (availability.outChipText !== null && availability.outChipTitle !== null) {
    chips.push({
      kind: "out",
      tone: "destructive",
      text: availability.outChipText,
      label: availability.outChipText,
      description: availability.outChipTitle,
    });
  }
  if (
    isPartial &&
    projection.caveatLabel !== null &&
    partialDescription !== undefined
  ) {
    chips.push({
      kind: "partial",
      tone: "muted",
      text: PARTIAL_BADGE_TEXT,
      label: projection.caveatLabel,
      description: partialDescription,
      computedText,
    });
  }
  // The em dash state: there is no number, and no sentence to add to that.
  if (projection.caveat === "unavailable" && projection.caveatLabel !== null) {
    chips.push({
      kind: "unavailable",
      tone: "muted",
      text: projection.caveatLabel,
      label: projection.caveatLabel,
    });
  }
  if (team.isEliminated) {
    chips.push({
      kind: "eliminated",
      tone: "muted",
      text: eliminatedText,
      label: eliminatedText,
      description:
        team.eliminationSource === "sleeper_inferred"
          ? PROVISIONAL_ELIMINATION_TITLE
          : undefined,
    });
  }

  // Past two, no reserve leaves the name anything to read, so the chips give the line back and
  // stack in the row below the summary instead. Both rows are always mounted, so this is a
  // change of which row holds the chips, never a row appearing on one card and not another.
  const isStacked = chips.length >= CHIP_STACK_THRESHOLD;
  const overlayChips: SummaryChipProps[] = isStacked ? [] : chips;
  const stackedChips: SummaryChipProps[] = isStacked ? chips : [];
  const ownerNameReserveClass =
    OWNER_NAME_RESERVE_CLASSES[overlayChips.length] ?? "";

  return (
    <li>
      {/*
        An eliminated card is dimmed in its chrome only — a muted fill and a dashed border. The
        card carried `opacity-60` before, which faded the text along with everything else and
        dropped the owner name and projection below the contrast floor for the very readers who
        most need them. `data-eliminated` is the state's stable, styling-independent handle.
      */}
      <Card
        data-eliminated={team.isEliminated || undefined}
        className={cn(
          TEAM_CARD_CLASS,
          "overflow-hidden",
          team.isEliminated && "border-dashed bg-muted/60",
        )}
      >
        <Collapsible open={isOpen}>
          {/*
            The whole summary is one button: the projection number is the part of a card a thumb
            actually lands on, and splitting it to give a badge its own control cost the card
            that target once already. The chips are a sibling laid over the end of the owner's
            line by the grid — inside the button they could not be tooltip triggers, and a
            control inside a `<button>` is invalid HTML. The chevron keeps its own 44px target
            in the second column.
          */}
          <div
            data-card-summary
            className={cn(
              "grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-2 p-4",
              SUMMARY_MIN_HEIGHT_CLASS,
            )}
          >
            {/* A real <button>, not a Radix trigger, so the card owns its `aria-controls`. */}
            <button
              type="button"
              aria-expanded={isOpen}
              aria-controls={panelId}
              onClick={() => onToggle(team.teamId)}
              className={cn(
                "col-start-1 row-start-1 flex min-h-[44px] min-w-0 items-start gap-3 text-left",
                FOCUS_RING_CLASS,
              )}
            >
              <span className="w-5 shrink-0 pt-1 text-sm tabular-nums text-muted-foreground">
                {rank}
              </span>
              <span className="min-w-0 flex-1">
                {/*
                  The owner's line. Ben: "I'd prefer the badge by the owner's name." The chips
                  are overlaid on the end of this line from outside the button, so the name
                  reserves room for them and truncates into it — as much room as the chips
                  actually rendered need, and none at all on the many cards that have none.
                */}
                <span
                  data-owner-name
                  className={cn(
                    "block truncate font-medium text-foreground",
                    ownerNameReserveClass,
                  )}
                >
                  {/* Full-strength foreground even when eliminated; only the chrome dims. */}
                  {team.ownerName}
                </span>
                <span className="block truncate text-sm text-muted-foreground">
                  {team.teamName}
                </span>
                <span className="mt-1 block truncate text-xs text-muted-foreground">
                  {/*
                    Ben's card change 1: the season total, not a record and not "points for".
                    The visible word is `Total`; the sr-only copy names the figure in full, so
                    the line is not read out as a total of something unstated.
                  */}
                  <span aria-hidden="true">{`${TOTAL_POINTS_TEXT} ${totalPoints}`}</span>
                  <span className="sr-only">{`${TOTAL_POINTS_LABEL} ${totalPoints}`}</span>
                  {` · ${faab}`}
                </span>
              </span>

              {/*
                The projection and what qualifies it: the number, its caption and the empty-slot
                count. A lineup with a hole in it has to be visible without expanding the card.
                Spans, not a <div>, because this block lives inside the toggle button.
              */}
              <span
                data-projection
                className={cn("shrink-0 text-right", PROJECTION_WIDTH_CLASS)}
              >
                <span className="block text-2xl font-semibold tabular-nums text-foreground">
                  {projection.text}
                </span>
                <span className="block text-xs text-muted-foreground">
                  proj
                </span>
                {emptySlots > 0 ? (
                  <span className="mt-1 block text-xs font-medium text-destructive">
                    {`${emptySlots} empty`}
                    <span className="sr-only">{` ${EMPTY_SLOTS_DESCRIPTION}`}</span>
                  </span>
                ) : null}
              </span>
            </button>

            {/*
              Everything that qualifies this card, on one row at the end of the owner's line.

              Always mounted, chips or not, and with a floor of its own, so the summary has one
              structure and one height rather than two: a row that appeared and disappeared —
              the badge row that used to sit *below* the summary, holding the elimination and
              `Projection unavailable` badges — is what was changing the card's height, so those
              two badges are chips in this row now as well.

              It sits in the toggle's own grid cell, right-aligned and top-aligned above it,
              reserving the projection block's width so a chip never lands on the number. The row
              is inert (`pointer-events-none`) and the chips take their events back one by one,
              so an empty row never swallows a tap meant for the card.

              It holds at most two chips, because the name it is laid over has to keep some of
              its own line; a third sends all of them to the stacked row below.
            */}
            <div
              data-chip-row
              className={cn(
                "pointer-events-none z-10 col-start-1 row-start-1 flex max-w-full flex-nowrap items-center justify-end gap-1 self-start justify-self-end overflow-hidden",
                CHIP_ROW_MIN_HEIGHT_CLASS,
                CHIP_ROW_RESERVE_CLASS,
              )}
            >
              {overlayChips.map((chip) => (
                <SummaryChip key={chip.kind} {...chip} />
              ))}
            </div>

            {/*
              A redundant mouse and touch target for the same toggle, hidden from assistive
              technology and out of the tab order: the button above is the one control, and a
              second `aria-expanded` on the same panel would only be read twice.
            */}
            <button
              type="button"
              tabIndex={-1}
              aria-hidden="true"
              onClick={() => onToggle(team.teamId)}
              className="col-start-2 row-start-1 flex min-h-[44px] min-w-[44px] shrink-0 items-start justify-center pt-1"
            >
              <ChevronDown
                aria-hidden="true"
                className={cn(
                  "h-4 w-4 text-muted-foreground transition-transform motion-reduce:transition-none",
                  isOpen && "rotate-180",
                )}
              />
            </button>

            {/*
              Where the chips go when there are more of them than the owner's line can hold: a
              row of their own, under the summary line and across the full width of the card,
              with the whole card's width to spread into rather than the end of a name.

              Mounted on every card and floored at the same 44px whether or not it holds
              anything, for the reason the overlay row is: a row that appears on the one card
              carrying three chips is exactly the height difference Ben asked to be rid of. It
              is inert, like the other row, and each chip takes its own events back.
            */}
            <div
              data-chip-stack
              className={cn(
                "pointer-events-none col-span-2 col-start-1 row-start-2 flex flex-nowrap items-center gap-1 overflow-hidden",
                CHIP_ROW_MIN_HEIGHT_CLASS,
              )}
            >
              {stackedChips.map((chip) => (
                <SummaryChip key={chip.kind} {...chip} />
              ))}
            </div>
          </div>

          {/*
            The panel element is force-mounted and hidden with the `hidden` attribute rather than
            unmounted, so the `aria-controls` above always resolves to a real element. Its
            *contents* are still mounted lazily: `forceMount` alone would render every collapsed
            team's full roster into the DOM, so a twelve-team board would carry a couple of
            hundred hidden rows that re-render on every realtime invalidation for nobody's
            benefit. An empty box is all `aria-controls` needs.
          */}
          <CollapsibleContent id={panelId} forceMount hidden={!isOpen}>
            {isOpen ? (
              <CardContent className="border-t pt-4">
                {team.isRosterFrozen ? (
                  <p className="mb-2 text-xs text-muted-foreground">
                    {FROZEN_ROSTER_LABEL}
                  </p>
                ) : null}
                <RosterPanel
                  players={team.roster}
                  starterSlots={starterRows}
                  highlightedPlayerIds={highlightedPlayerIds}
                />
              </CardContent>
            ) : null}
          </CollapsibleContent>
        </Collapsible>
      </Card>
    </li>
  );
});
