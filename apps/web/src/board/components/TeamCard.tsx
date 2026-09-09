import { memo, useId, useMemo } from "react";
import { ChevronDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

import { resolveProjectionDisplay } from "../derive/projection";
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

/** Decimals the points-for figure is shown with. */
const POINTS_FOR_DECIMALS = 1;

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
  const record = `${team.wins}-${team.losses}${
    team.ties > 0 ? `-${team.ties}` : ""
  }`;
  const faab =
    team.faabRemaining === null
      ? FAAB_UNKNOWN_TEXT
      : `${team.faabRemaining} FAAB`;
  // Only the partial badge carries a computed-at tooltip: it is the one caveat where the age of
  // the number is the follow-up question. `Projection unavailable` means there is no number to
  // have been computed, so a "computed at" time on it would be a lie about a row that is absent.
  // A raw ISO timestamp is never surfaced (see `derive/time`), so it is formatted in the
  // viewer's own locale and timezone like every other time on the board.
  const computedTitle =
    projection.caveat === "partial" && team.projectionComputedAt !== null
      ? formatComputedTitle(Date.parse(team.projectionComputedAt))
      : undefined;
  const hasBadges = projection.caveatLabel !== null || team.isEliminated;

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
            A real <button>, not a Radix trigger, so the card owns its `aria-controls`. The
            badges sit outside it because `Badge` renders a <div>, and a <div> inside a <button>
            is invalid HTML.
          */}
          <button
            type="button"
            aria-expanded={isOpen}
            aria-controls={panelId}
            onClick={() => onToggle(team.teamId)}
            className={cn(
              "flex min-h-[44px] w-full items-start gap-3 p-4 text-left",
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
                {record} · {team.pointsFor.toFixed(POINTS_FOR_DECIMALS)} PF ·{" "}
                {faab}
              </span>
            </span>
            <span className="shrink-0 text-right">
              <span className="block text-2xl font-semibold tabular-nums text-foreground">
                {projection.text}
              </span>
              <span className="block text-xs text-muted-foreground">proj</span>
              {/*
                Inside the summary button, not in the badge row below it: a lineup with a hole
                in it has to be visible without expanding the card. A plain span rather than a
                `Badge`, which renders a <div> and would be invalid HTML inside a <button>.
              */}
              {emptySlots > 0 ? (
                <span className="mt-1 block text-xs font-medium text-destructive">
                  {`${emptySlots} empty`}
                  <span className="sr-only">{` ${EMPTY_SLOTS_DESCRIPTION}`}</span>
                </span>
              ) : null}
            </span>
            <ChevronDown
              aria-hidden="true"
              className={cn(
                "mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none",
                isOpen && "rotate-180",
              )}
            />
          </button>

          {hasBadges ? (
            <div className="flex flex-wrap gap-2 px-4 pb-3">
              {projection.caveatLabel === null ? null : (
                <Badge variant="outline" title={computedTitle}>
                  {projection.caveat === "partial" ? (
                    <>
                      {/* Below the gate the number still shows; the badge is only a footnote. */}
                      <span aria-hidden="true">{PARTIAL_BADGE_TEXT}</span>
                      <span className="sr-only">{projection.caveatLabel}</span>
                    </>
                  ) : (
                    projection.caveatLabel
                  )}
                </Badge>
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
