import { memo, useId, useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

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

/** Label for a team eliminated in a week the data layer does not know yet. */
const ELIMINATED_LABEL = "Eliminated";

/** The tooltip a Sleeper-inferred elimination carries; the label itself stays plain. */
const PROVISIONAL_ELIMINATION_TITLE =
  "Provisional: inferred from Sleeper, not yet ruled by the Adjudicator";

/** Said once above a frozen roster, so the reader knows why it never changes again. */
export const FROZEN_ROSTER_LABEL = "Final roster, frozen at elimination";

/** What the empty-slot count is called for a reader who cannot see it sitting under `proj`. */
const EMPTY_SLOTS_DESCRIPTION = "empty starter slots";

interface PartialCoverageBadgeProps {
  /** The sentence that says why the badge is there; the tooltip's whole point. */
  description: string;
  /** What the badge is called; the same wording the screen reader hears. */
  label: string;
  /** When the projection was computed, already in words. Omitted when it is not known. */
  computedText: string | undefined;
}

/**
 * The `partial` badge, under the projection it is about.
 *
 * Ben's card change 3: the badge used to sit in the row of badges below the summary, far enough
 * from the number that it read as a property of the card rather than of the projection, and it
 * never said why it was there. So it moved under the big number, and it explains itself.
 *
 * The tooltip is controlled rather than left to Radix's hover-and-focus default: Radix suppresses
 * tooltips opened by touch, and this badge is read on a phone as often as anywhere. Hover and
 * keyboard focus still open it through `onOpenChange`; the click handler adds tap. The sentence
 * is also mounted as visually hidden text and named by `aria-describedby`, so a screen reader
 * gets it whether or not the tooltip is open.
 */
function PartialCoverageBadge({
  description,
  label,
  computedText,
}: PartialCoverageBadgeProps) {
  const [open, setOpen] = useState(false);
  const descriptionId = useId();

  return (
    <TooltipProvider>
      <Tooltip open={open} onOpenChange={setOpen}>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-describedby={descriptionId}
            onClick={() => setOpen((wasOpen) => !wasOpen)}
            className={cn(
              "inline-flex min-h-[44px] items-center justify-end rounded-md",
              FOCUS_RING_CLASS,
            )}
          >
            {/* Below the gate the number still shows; the badge is only a footnote. */}
            <span
              aria-hidden="true"
              className="rounded-md border px-2 py-0.5 text-xs font-medium text-muted-foreground"
            >
              {PARTIAL_BADGE_TEXT}
            </span>
            <span className="sr-only">{label}</span>
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-[16rem] text-left">
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
}

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
 * One team's row on the board: the summary line, its caveat badges, and the roster panel the
 * summary expands into. Open state is owned by the caller so only one card need be open at a
 * time and so the board can restore it from the URL.
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
  // Laid out once per card rather than once per open card: the count below the projection is
  // on the collapsed card too, which is the point — Ben should not have to expand nine cards to
  // find the one missing a flex.
  const starterSlots = useMemo(
    () => layoutStarters(rosterPositions, team.roster),
    [rosterPositions, team.roster],
  );
  const emptySlots = resolveEmptySlotCount(team.emptySlots, starterSlots);
  const projection = resolveProjectionDisplay(team);
  const totalPoints = team.pointsFor.toFixed(TOTAL_POINTS_DECIMALS);
  const faab =
    team.faabRemaining === null
      ? FAAB_UNKNOWN_TEXT
      : `${team.faabRemaining} FAAB`;
  // Only the partial badge carries a computed-at line: it is the one caveat where the age of
  // the number is the follow-up question. `Projection unavailable` means there is no number to
  // have been computed, so a "computed at" time on it would be a lie about a row that is absent.
  // A raw ISO timestamp is never surfaced (see `derive/time`), so it is formatted in the
  // viewer's own locale and timezone like every other time on the board.
  const computedText =
    projection.caveat === "partial" && team.projectionComputedAt !== null
      ? formatComputedTitle(Date.parse(team.projectionComputedAt))
      : undefined;
  // The partial caveat left this row when it moved under the projection, so the row below the
  // summary is now the unavailable caveat and the elimination badge — and nothing at all for a
  // live team with a good projection, which is most of the board.
  const isPartial = projection.caveat === "partial";
  const coverageExplanation = partialCoverageExplanation(team);
  const hasBadges =
    (projection.caveatLabel !== null && !isPartial) || team.isEliminated;

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
            The summary is a row of three, not one button: the projection block beside the
            toggle now holds the `partial` badge, which owns a tooltip and so has to be a
            control of its own — and a control inside a <button> is invalid HTML. The toggle
            still covers the owner, the team and the numbers line, which is the whole left of
            the row; the chevron keeps its own 44px target so tapping it still expands.
          */}
          <div data-card-summary className="flex items-start gap-2 p-4">
            {/* A real <button>, not a Radix trigger, so the card owns its `aria-controls`. */}
            <button
              type="button"
              aria-expanded={isOpen}
              aria-controls={panelId}
              onClick={() => onToggle(team.teamId)}
              className={cn(
                "flex min-h-[44px] min-w-0 flex-1 items-start gap-3 text-left",
                FOCUS_RING_CLASS,
              )}
            >
              <span className="w-5 shrink-0 pt-1 text-sm tabular-nums text-muted-foreground">
                {rank}
              </span>
              <span className="min-w-0 flex-1">
                {/* Full-strength foreground even when eliminated; only the chrome dims. */}
                <span className="block truncate font-medium text-foreground">
                  {team.ownerName}
                </span>
                <span className="block truncate text-sm text-muted-foreground">
                  {team.teamName}
                </span>
                <span className="mt-1 block text-xs text-muted-foreground">
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
            </button>

            {/*
              The projection and everything that qualifies it: the number, its caption, the
              `partial` badge when the coverage is below the gate, and the empty-slot count. A
              lineup with a hole in it, or a projection built on half a lineup, has to be
              visible without expanding the card.
            */}
            <div data-projection className="shrink-0 text-right">
              <span className="block text-2xl font-semibold tabular-nums text-foreground">
                {projection.text}
              </span>
              <span className="block text-xs text-muted-foreground">proj</span>
              {isPartial && projection.caveatLabel !== null ? (
                <PartialCoverageBadge
                  description={coverageExplanation ?? projection.caveatLabel}
                  label={projection.caveatLabel}
                  computedText={computedText}
                />
              ) : null}
              {emptySlots > 0 ? (
                <span className="mt-1 block text-xs font-medium text-destructive">
                  {`${emptySlots} empty`}
                  <span className="sr-only">{` ${EMPTY_SLOTS_DESCRIPTION}`}</span>
                </span>
              ) : null}
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
              className="flex min-h-[44px] min-w-[44px] shrink-0 items-start justify-center pt-1"
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
              {/* Only the em dash state lands here now; `partial` sits under the number. */}
              {projection.caveatLabel === null || isPartial ? null : (
                <Badge variant="outline">{projection.caveatLabel}</Badge>
              )}
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
                  starterSlots={starterSlots}
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
