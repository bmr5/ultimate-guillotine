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
import { resolveChipKinds, type ChipKind } from "../derive/chips";
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
  "ring-offset-background focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

/**
 * The same ring for a chip, drawn *inside* the chip instead of around it.
 *
 * The chip line is `h-6 overflow-hidden`, and a chip fills it: an offset ring is drawn two
 * pixels outside the chip's own box, which is two pixels outside the line, so the clipping that
 * keeps the line to 24px was cutting the focus ring off the one control on the card that is
 * hardest to see. `ring-inset` puts it on the chip's own border instead, where nothing clips it,
 * and `ring-offset-background` goes with the offset it no longer has.
 */
const CHIP_FOCUS_RING_CLASS =
  "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring";

/** The short, visible form of the below-gate caveat; the full label rides along for readers. */
const PARTIAL_BADGE_TEXT = "partial";

/**
 * The collapsed summary's height, so every card in the grid is the same one.
 *
 * Ben's addendum: "make every card the same height — the badge currently changes card height."
 * A `min-h` alone would not do it; it works because every line inside the summary is bounded and
 * both rows are mounted on every card whatever it has to say.
 *
 * The arithmetic, from the line heights this markup actually uses (16px root):
 *
 * - row 1, the owner block: name 24px (inherited 1rem/1.5) + team name 20px (`text-sm`) +
 *   `mt-1` 4px + total line 16px (`text-xs`) = **64px**;
 * - row 1, the projection block beside it: 32px (`text-2xl`) + `proj` 16px + `mt-1` 4px +
 *   empty-slot count 16px = **68px**, which is the taller of the two and so the row;
 * - row 2, the chip line: `mt-1` 4px + `h-6` 24px = **28px**;
 * - the card's own `p-4`: 32px.
 *
 * 32 + 68 + 28 = **128px = 8rem**. The ruling estimated 7.75rem from the owner block alone; the
 * extra quarter-rem is the `N empty` line under `proj`, which is the taller column whenever a
 * lineup has a hole in it, and a floor that did not clear it would let exactly those cards grow.
 * The toggle's own `min-h-[44px]` is well under the row it sits in and never binds.
 */
export const SUMMARY_MIN_HEIGHT_CLASS = "min-h-32";

/**
 * The chip line's height, fixed rather than floored, so the line occupies the same band on every
 * card whether it holds two chips or none — that is what makes the equal height structural
 * instead of a coincidence of what each card happens to say. The chips are the same height as
 * the line they sit on.
 *
 * 24px, not the 44px touch target the overlaid row carried through rounds 1–3: a chip no longer
 * covers anything, so its target need not be big enough to be dodged. The chip's own 11px face
 * (`CHIP_FACE_CLASS`) measures 22px with its padding and border, and centres inside this.
 */
export const CHIP_ROW_HEIGHT_CLASS = "h-6";

/**
 * The chip line's indent, so the chips start at the owner name's left edge rather than at the
 * card's: the rank column's `w-5` (20px) plus the toggle's `gap-3` (12px) is 32px = `pl-8`.
 */
export const CHIP_ROW_INDENT_CLASS = "pl-8";

/**
 * The projection block's width. Fixed so the numbers line up down the grid.
 *
 * It used to do a second job — the chip row overlaid on the owner's line reserved exactly this
 * much plus the toggle's `gap-3`, so a chip never landed on the number. Round 3 measured that
 * geometry on a 375px card and it does not fit: the name field is 141px and a two-chip set is
 * 139px. The chips have their own line now, and nothing reserves against this any more.
 */
const PROJECTION_WIDTH_CLASS = "w-18";

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
  kind: ChipKind;
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
 * One chip on the line under the owner's name.
 *
 * Ben asked for the badge "by the owner's name". The chips are a *sibling* of the summary
 * toggle, on the summary grid's second row rather than nested inside the button — a control
 * inside a `<button>` is invalid HTML, and it was what cost the card its whole-card tap target
 * the last time. Outside it, a chip can be a real Radix tooltip trigger, which is the point: the
 * native `title` this replaced never opened on a tap, and a phone is where this board is read.
 *
 * They sat *on* the owner's line through rounds 1–3, overlaid from outside the button and dodged
 * by a reserve on the name. Round 3 measured that on a 375px card: 141px of name field against
 * 139px of chips, and no reserve fixes it. A line of their own costs 28px of card and gives the
 * name its whole width back.
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
          CHIP_ROW_HEIGHT_CLASS,
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
              // The chip covers nothing now, so it needs no `pointer-events-auto` to take its
              // own taps back and no 44px target to keep the card's line reachable around it.
              "inline-flex shrink-0 items-center whitespace-nowrap rounded-md",
              CHIP_ROW_HEIGHT_CLASS,
              CHIP_TEXT_CLASS[tone],
              CHIP_FOCUS_RING_CLASS,
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

  // What each state would say, if the card is allowed to say it. Building the wording is not
  // deciding to show it: `resolveChipKinds` owns that, in one place, so the mutual exclusions
  // read as a rule rather than as four conditions that happen to agree.
  const chipCopy: Partial<Record<ChipKind, SummaryChipProps>> = {};
  if (availability.outChipText !== null && availability.outChipTitle !== null) {
    chipCopy.out = {
      kind: "out",
      tone: "destructive",
      text: availability.outChipText,
      label: availability.outChipText,
      description: availability.outChipTitle,
    };
  }
  if (projection.caveatLabel !== null && partialDescription !== undefined) {
    chipCopy.partial = {
      kind: "partial",
      tone: "muted",
      text: PARTIAL_BADGE_TEXT,
      label: projection.caveatLabel,
      description: partialDescription,
      computedText,
    };
  }
  // The em dash state: there is no number, and no sentence to add to that.
  if (projection.caveat === "unavailable" && projection.caveatLabel !== null) {
    chipCopy.unavailable = {
      kind: "unavailable",
      tone: "muted",
      text: projection.caveatLabel,
      label: projection.caveatLabel,
    };
  }
  chipCopy.eliminated = {
    kind: "eliminated",
    tone: "muted",
    text: eliminatedText,
    label: eliminatedText,
    description:
      team.eliminationSource === "sleeper_inferred"
        ? PROVISIONAL_ELIMINATION_TITLE
        : undefined,
  };

  // The ruling after fix round 2: the chip set is mutually limited, so a card carries at most
  // two short chips. They no longer have to fit beside the name — they have their own line — but
  // the limit is still what keeps that line to one row of `flex-nowrap`.
  const chips = resolveChipKinds({
    isEliminated: team.isEliminated,
    hasProjection: projection.kind === "value",
    outCount: availability.outCount,
    isPartial,
  })
    .map((kind) => chipCopy[kind])
    .filter((chip): chip is SummaryChipProps => chip !== undefined);

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
            Two grid rows. Row 1 is the whole summary as one button — the projection number is
            the part of a card a thumb actually lands on, and splitting it to give a badge its
            own control cost the card that target once already — with the chevron's own 44px
            target beside it in column 2. Row 2 is the chip line, a sibling of the button because
            inside it the chips could not be tooltip triggers and a control inside a `<button>`
            is invalid HTML.
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
                  are on the line below, indented to this one's left edge, so the name keeps the
                  whole column and truncates only against the projection beside it. It reserved
                  room for overlaid chips until round 3 measured that reserve as the entire name
                  field on a 375px phone.
                */}
                <span
                  data-owner-name
                  className="block truncate font-medium text-foreground"
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
              Everything that qualifies this card, on a line of its own under the owner's name.

              Always mounted, chips or not, and a fixed height rather than a floor, so the summary
              has one structure and one height rather than two: a row that appeared and
              disappeared — the badge row that used to sit below the summary, holding the
              elimination and `Projection unavailable` badges — is what was changing the card's
              height, so those two badges are chips in this line as well.

              It covers nothing, so it needs no `pointer-events-none`: an empty line has no
              children and is inert by having nothing in it, and a chip stays clickable without
              taking its own events back. `flex-nowrap` with `overflow-hidden` keeps it to one
              line whatever it holds; it holds at most two chips, which is a property of the chip
              set rather than of this line — see `derive/chips.ts`.
            */}
            <div
              data-chip-row
              className={cn(
                "col-start-1 row-start-2 mt-1 flex flex-nowrap items-center gap-1 overflow-hidden",
                CHIP_ROW_HEIGHT_CLASS,
                CHIP_ROW_INDENT_CLASS,
              )}
            >
              {chips.map((chip) => (
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
