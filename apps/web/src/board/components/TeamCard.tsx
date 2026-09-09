import { memo, useId, useMemo } from "react";
import { ChevronDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

import { resolveStarterAvailability } from "../derive/availability";
import {
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
 * The owner line, the team name and the total line each truncate to one line, the chip row
 * never wraps, and the projection block is at most three lines (number, `proj`, empty count).
 * 6.5rem clears that tallest case with the card's `p-4` around it, so a card with chips, a card
 * with an empty-slot count and a plain card all measure the same.
 */
const SUMMARY_MIN_HEIGHT_CLASS = "min-h-[6.5rem]";

/** Label for a team eliminated in a week the data layer does not know yet. */
const ELIMINATED_LABEL = "Eliminated";

/** The tooltip a Sleeper-inferred elimination carries; the label itself stays plain. */
const PROVISIONAL_ELIMINATION_TITLE =
  "Provisional: inferred from Sleeper, not yet ruled by the Adjudicator";

/** Said once above a frozen roster, so the reader knows why it never changes again. */
export const FROZEN_ROSTER_LABEL = "Final roster, frozen at elimination";

/** What the empty-slot count is called for a reader who cannot see it sitting under `proj`. */
const EMPTY_SLOTS_DESCRIPTION = "empty starter slots";

interface SummaryChipProps {
  /** The `data-chip` handle, so a test names the state rather than the styling. */
  kind: "out" | "partial";
  /** The short, visible wording. */
  text: string;
  /** The sentence behind it, as the native tooltip a reader hovers. */
  title: string;
  /** The same thing spelled out for a screen reader, whether or not the tooltip is open. */
  label: string;
  /** `destructive` for something costing points now; `muted` for a footnote on the number. */
  tone: "destructive" | "muted";
}

/**
 * One chip on the owner's line.
 *
 * Ben asked for the badge "by the owner's name", which puts it inside the summary toggle — and a
 * control nested in a `<button>` is invalid HTML and a dead tooltip besides. So the chips are
 * plain spans and the explanation is a native `title` rather than the Radix tooltip the badge
 * carried under the projection. The trade is deliberate: a `title` does not open on tap, so the
 * sentence is also mounted as visually hidden text, which is what a screen reader and a phone
 * reader actually get. The elimination badge below the summary has always worked this way.
 *
 * `shrink-0` and `whitespace-nowrap` keep a chip on one line; the row around it clips.
 */
const SummaryChip = memo(function SummaryChip({
  kind,
  text,
  title,
  label,
  tone,
}: SummaryChipProps) {
  return (
    <span
      data-chip={kind}
      title={title}
      className={cn(
        "shrink-0 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[0.6875rem] font-medium leading-4",
        tone === "destructive"
          ? "border-destructive/40 text-destructive"
          : "border-border text-muted-foreground",
      )}
    >
      <span aria-hidden="true">{text}</span>
      <span className="sr-only">{label}</span>
    </span>
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
  // Both have to agree: the data layer says the week is short, and the shortfall is not
  // explained by who is injured. Either alone would put the chip on the wrong cards.
  const isPartial = projection.caveat === "partial" && availability.isPartial;

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
  const partialTitle = [
    coverageExplanation ?? projection.caveatLabel ?? "",
    computedText ?? "",
  ]
    .filter((line) => line !== "")
    .join("\n");
  // The chips left this row when they moved onto the owner's line, so what is left below the
  // summary is the unavailable caveat and the elimination badge — and nothing at all for a live
  // team with a good projection, which is most of the board.
  const hasBadges =
    (projection.caveatLabel !== null && projection.caveat === "unavailable") ||
    team.isEliminated;

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
            that target once already. The chips are spans, not controls, so they can sit inside
            it. The chevron keeps its own 44px target in the second column.
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
                  The owner's line, and the chips that qualify this card, on it. Ben: "I'd
                  prefer the badge by the owner's name." One line, always: the name truncates
                  and the chip row clips rather than wrapping, so no combination of chips can
                  make this card taller than its neighbours.
                */}
                <span className="flex min-w-0 items-center gap-1.5">
                  {/* Full-strength foreground even when eliminated; only the chrome dims. */}
                  <span className="min-w-0 truncate font-medium text-foreground">
                    {team.ownerName}
                  </span>
                  {/*
                    Always mounted, chips or not, so the summary has one structure rather than
                    two: an element that appears and disappears is exactly what was changing the
                    card's height. Empty it collapses to nothing and costs no space.
                  */}
                  <span
                    data-chip-row
                    className="flex min-w-0 shrink flex-nowrap items-center gap-1 overflow-hidden"
                  >
                    {availability.outChipText === null ||
                    availability.outChipTitle === null ? null : (
                      <SummaryChip
                        kind="out"
                        tone="destructive"
                        text={availability.outChipText}
                        title={availability.outChipTitle}
                        label={`${availability.outChipText}. ${availability.outChipTitle}`}
                      />
                    )}
                    {isPartial && projection.caveatLabel !== null ? (
                      <SummaryChip
                        kind="partial"
                        tone="muted"
                        text={PARTIAL_BADGE_TEXT}
                        title={partialTitle}
                        label={`${projection.caveatLabel}. ${partialTitle}`}
                      />
                    ) : null}
                  </span>
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
              <span data-projection className="shrink-0 text-right">
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

          {hasBadges ? (
            <div className="flex flex-wrap gap-2 px-4 pb-3">
              {/* Only the em dash state lands here now; the chips sit on the owner's line. */}
              {projection.caveat === "unavailable" &&
              projection.caveatLabel !== null ? (
                <Badge variant="outline">{projection.caveatLabel}</Badge>
              ) : null}
              {team.isEliminated ? (
                <Badge
                  variant="secondary"
                  title={
                    team.eliminationSource === "sleeper_inferred"
                      ? PROVISIONAL_ELIMINATION_TITLE
                      : undefined
                  }
                >
                  {team.eliminatedWeek === null
                    ? ELIMINATED_LABEL
                    : `${ELIMINATED_LABEL} week ${team.eliminatedWeek}`}
                </Badge>
              ) : null}
            </div>
          ) : null}

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
