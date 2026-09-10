import { memo, useId, useMemo } from "react";
import { ChevronDown } from "lucide-react";

import { ExplainedBadge } from "@/components/explained-badge";
import { badgeVariants } from "@/components/ui/badge-variants";
import { Card, CardContent } from "@/components/ui/card";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { REVEAL_CLASS, revealStyle } from "@/motion/reveal";

import { injuryTag } from "../derive/availability";
import { FAAB_LABEL, formatFaab } from "../derive/faab";
import {
  LIKELY_BIDDER_REASONS,
  likelyBidderFigures,
  slotDescription,
  type PositionRow,
} from "../derive/position";
import { layoutStarters } from "../derive/roster";
import { BOARD_GRID, LIVE_SCORE_PILL_CLASS } from "../layout";
import type { PositionFilter } from "../types";
import { PlayerName } from "./PlayerName";
import { RosterPanel } from "./RosterPanel";

/** The badge a team likely to bid on this position carries; also what the tests assert on. */
export const LIKELY_BIDDER_LABEL = "likely bidder";

/**
 * The sentence behind the badge when the derivation flagged a team without saying which of its
 * reasons fired. `derivePositionRows` always sets one today, so this is the honest fallback
 * rather than an empty tooltip.
 */
const LIKELY_BIDDER_FALLBACK_DESCRIPTION =
  "This team looks thin at the position and may bid on a replacement";

/** Decimals a player projection is shown with, matching every other number on the board. */
const PLAYER_PROJECTION_DECIMALS = 1;

/** The board's stand-in for "there is no number here"; never a zero. */
const NO_PROJECTION_TEXT = "—";

/**
 * A starter's live figure, ahead of his projection: `12.4 / 14.1`. Same pairing the roster
 * panel uses, minus the `proj` word — this view lists several players on one line and the
 * column has no room for it, so the wording rides along for a screen reader instead.
 *
 * Starters only, for the same reason: a bench player's live points are real but they are not
 * part of this week's total, and every row carrying two numbers would bury the ones that are.
 */
const LIVE_POINTS_SEPARATOR = "/";
const LIVE_POINTS_LABEL = "scored";
const PROJECTED_LABEL = "projected";

/** Said once per team that holds nobody at the position: `no TE`. */
const NO_PLAYER_PREFIX = "no";

/**
 * How the empty-slot count reads for a reader who cannot see it beside the FAAB figure.
 *
 * The position is named: this count is not the card's, which is every unfilled slot in the
 * lineup. Here it is only the slots *this* position could fill — a FLEX counts for a tight end
 * but a K slot does not — so `empty TE slots` is the honest reading of the same "2 empty".
 */
const emptySlotsDescription = (position: PositionFilter) =>
  `empty ${position} slots`;

/**
 * The same focus ring the header's controls and the team card's summary carry. These rows are
 * bare `<button>`s rather than `Button`s, so they have to name it themselves.
 */
const FOCUS_RING_CLASS =
  "ring-offset-background focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

function projectionText(points: number | null): string {
  return points === null
    ? NO_PROJECTION_TEXT
    : points.toFixed(PLAYER_PROJECTION_DECIMALS);
}

interface PositionTeamRowProps {
  row: PositionRow;
  position: PositionFilter;
  isOpen: boolean;
  onToggle: (teamId: number) => void;
  highlightedPlayerIds: ReadonlySet<string>;
  rosterPositions: string[];
  /** Opens a player's card from his name; the page owns the URL it writes. */
  onOpenPlayer: (sleeperPlayerId: string) => void;
  /** The row's place in the page's cascade; the header is place 0. */
  revealIndex: number;
}

/**
 * One team at one position: the owner, what is left to bid with, who they hold there, and
 * whether the board thinks they are in the market. Memoised for the same reason `TeamCard` is —
 * eighteen of these re-render on every realtime invalidation otherwise.
 */
const PositionTeamRow = memo(function PositionTeamRow({
  row,
  position,
  isOpen,
  onToggle,
  highlightedPlayerIds,
  rosterPositions,
  onOpenPlayer,
  revealIndex,
}: PositionTeamRowProps) {
  const panelId = useId();
  const starterSlots = useMemo(
    () => layoutStarters(rosterPositions, row.team.roster),
    [rosterPositions, row.team.roster],
  );
  const faab = formatFaab(row.faabRemaining);

  return (
    <li className={REVEAL_CLASS} style={revealStyle(revealIndex)}>
      {/* Eliminated teams are dimmed in their chrome only, never in their text. */}
      <Card
        data-eliminated={row.isEliminated || undefined}
        className={cn(
          "overflow-hidden",
          row.isEliminated && "border-dashed bg-background/50",
        )}
      >
        <Collapsible open={isOpen}>
          {/* A real <button>, so this row owns its `aria-controls`; badges sit outside it
              because `Badge` renders a <div>, which is invalid inside a <button>. */}
          <button
            type="button"
            aria-expanded={isOpen}
            aria-controls={panelId}
            onClick={() => onToggle(row.teamId)}
            className={cn(
              "flex min-h-[44px] w-full items-start gap-3 px-4 py-3 text-left",
              FOCUS_RING_CLASS,
            )}
          >
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium text-foreground">
                {row.ownerName}
              </span>
              <span className="block truncate text-sm text-muted-foreground">
                {row.teamName}
              </span>
            </span>
            <span className="shrink-0 text-right">
              <span className="block text-2xl leading-none figures text-foreground">
                {/* `$715` alone could be a price of anything: the sr-only copy names it. */}
                <span aria-hidden="true">{faab}</span>
                <span className="sr-only">{`${FAAB_LABEL} ${faab}`}</span>
              </span>
              {row.emptySlots > 0 ? (
                <span className="mt-1 block text-xs font-medium text-destructive">
                  {`${row.emptySlots} empty`}
                  <span className="sr-only">{` ${emptySlotsDescription(
                    position,
                  )}`}</span>
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

          {/* One player per line, outside the toggle: each slot chip and injury tag is a real
              tooltip trigger (Ben, 2026-09-10: "any little thing should have a tooltip"), and a
              control inside a <button> is invalid HTML. */}
          <ul
            className="space-y-1 px-4 pb-3 text-sm"
            aria-label={`${row.ownerName}'s ${position} players`}
          >
            {row.players.length === 0 ? (
              <li className="font-medium text-destructive">
                {`${NO_PLAYER_PREFIX} ${position}`}
              </li>
            ) : (
              row.players.map((player) => {
                const tag = injuryTag(player.injuryStatus);
                const highlighted = highlightedPlayerIds.has(
                  player.sleeperPlayerId,
                );
                return (
                  <li
                    key={player.sleeperPlayerId}
                    data-player={player.sleeperPlayerId}
                    data-starter={player.isStarter || undefined}
                    data-slot={player.slotLabel}
                    data-highlighted={highlighted || undefined}
                    className={cn(
                      "flex items-center gap-2",
                      highlighted &&
                        "rounded bg-accent px-1 text-accent-foreground",
                    )}
                  >
                    <ExplainedBadge
                      description={slotDescription(
                        player.slotLabel,
                        player.isStarter,
                      )}
                      className="-my-2 inline-flex min-h-[44px] items-center rounded-md"
                    >
                      <span
                        className={cn(
                          "inline-block w-14 rounded border px-1 text-center text-[0.6875rem] font-medium",
                          player.isStarter
                            ? "border-border text-foreground"
                            : "border-transparent text-muted-foreground",
                        )}
                      >
                        {player.slotLabel}
                      </span>
                    </ExplainedBadge>
                    <span className="flex min-w-0 flex-1 items-center gap-1">
                      <PlayerName
                        player={player}
                        ownerName={row.ownerName}
                        onOpen={onOpenPlayer}
                      />
                      <span className="shrink-0 text-muted-foreground tabular-nums">
                        {player.isStarter && player.livePoints !== null ? (
                          <>
                            <span
                              aria-hidden="true"
                              data-live-points
                              className={
                                player.livePoints === 0
                                  ? undefined
                                  : LIVE_SCORE_PILL_CLASS
                              }
                            >
                              {player.livePoints.toFixed(
                                PLAYER_PROJECTION_DECIMALS,
                              )}
                            </span>
                            <span aria-hidden="true">
                              {`${LIVE_POINTS_SEPARATOR}${projectionText(player.projectedPoints)}`}
                            </span>
                            <span className="sr-only">{`${LIVE_POINTS_LABEL} ${player.livePoints.toFixed(
                              PLAYER_PROJECTION_DECIMALS,
                            )}, ${PROJECTED_LABEL} ${projectionText(player.projectedPoints)}`}</span>
                          </>
                        ) : (
                          <>
                            <span aria-hidden="true">
                              {projectionText(player.projectedPoints)}
                            </span>
                            <span className="sr-only">{`${PROJECTED_LABEL} ${projectionText(
                              player.projectedPoints,
                            )}`}</span>
                          </>
                        )}
                      </span>
                    </span>
                    {tag === null ? null : (
                      <ExplainedBadge
                        data-injury={tag.status}
                        description={tag.title}
                        className="-my-2 inline-flex min-h-[44px] items-center rounded-md"
                      >
                        <span
                          className={cn(
                            "rounded border px-1 text-[0.6875rem] font-medium",
                            tag.isUnavailable
                              ? "border-destructive/40 text-destructive"
                              : "border-border text-muted-foreground",
                          )}
                        >
                          {tag.tag}
                        </span>
                      </ExplainedBadge>
                    )}
                  </li>
                );
              })
            )}
          </ul>

          {/* Ben's ruling of 2026-09-09: "I filtered by TE and a likely bidder showed up but I
              have no idea why". The reason used to be a native `title`, which never opens on a
              tap; now the badge is a real tooltip trigger with the reason behind it. And Ben
              (2026-09-10): "can you say what the actual median is?" — the figures the flag
              compared ride under the sentence as the tooltip's quieter second line. */}
          {row.likelyBidder ? (
            <div className="flex flex-wrap gap-2 px-4 pb-3">
              {/* The button is the 44px tap target every control in this view sits on; the
                  pill inside it is the badge a reader sees. The negative margin keeps the row
                  the height the pill alone would make it, so the floor costs no card height. */}
              <ExplainedBadge
                data-bidder-reason={row.likelyBidderReason ?? undefined}
                description={
                  row.likelyBidderReason === null
                    ? LIKELY_BIDDER_FALLBACK_DESCRIPTION
                    : LIKELY_BIDDER_REASONS[row.likelyBidderReason]
                }
                secondary={likelyBidderFigures(row) ?? undefined}
                className="-my-2.5 inline-flex min-h-[44px] items-center rounded-md"
              >
                <span className={badgeVariants({ variant: "outline" })}>
                  {LIKELY_BIDDER_LABEL}
                </span>
              </ExplainedBadge>
            </div>
          ) : null}

          {/* Force-mounted so `aria-controls` resolves, but empty until opened: a league-wide
              view is eighteen rosters, and mounting them all costs more than it shows. */}
          <CollapsibleContent id={panelId} forceMount hidden={!isOpen}>
            {isOpen ? (
              <CardContent className="border-t pt-4">
                <RosterPanel
                  players={row.team.roster}
                  starterSlots={starterSlots}
                  highlightedPlayerIds={highlightedPlayerIds}
                  ownerName={row.ownerName}
                  onOpenPlayer={onOpenPlayer}
                />
              </CardContent>
            ) : null}
          </CollapsibleContent>
        </Collapsible>
      </Card>
    </li>
  );
});

interface PositionViewProps {
  position: PositionFilter;
  rows: PositionRow[];
  isOpen: (teamId: number) => boolean;
  onToggle: (teamId: number) => void;
  highlightedPlayerIds: ReadonlySet<string>;
  rosterPositions: string[];
  onOpenPlayer: (sleeperPlayerId: string) => void;
}

/**
 * The whole league at one position, one row per team, in the order `positionView` decided.
 *
 * The same single column the board itself now holds (`BOARD_GRID`): the rows are wide and
 * shallow — owner, budget, the players inline — and reading down one column is how the question
 * is actually asked ("who would bid on a tight end?").
 */
export function PositionView({
  position,
  rows,
  isOpen,
  onToggle,
  highlightedPlayerIds,
  rosterPositions,
  onOpenPlayer,
}: PositionViewProps) {
  return (
    <ul className={BOARD_GRID}>
      {rows.map((row, index) => (
        <PositionTeamRow
          key={row.teamId}
          row={row}
          revealIndex={index + 1}
          position={position}
          isOpen={isOpen(row.teamId)}
          onToggle={onToggle}
          highlightedPlayerIds={highlightedPlayerIds}
          rosterPositions={rosterPositions}
          onOpenPlayer={onOpenPlayer}
        />
      ))}
    </ul>
  );
}
