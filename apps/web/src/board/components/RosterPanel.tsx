import { memo, useId } from "react";
import { AlertTriangle } from "lucide-react";

import { cn } from "@/lib/utils";

import {
  groupRosterBySlot,
  SLOT_LABELS,
  type StarterSlotRow,
} from "../derive/roster";
import type { RosterPlayer } from "../types";

/** The board's stand-in for "this player has no projection"; never a zero. */
const NO_PROJECTION_TEXT = "—";

/** Decimals a player projection is shown with, matching the team projection above it. */
const PLAYER_PROJECTION_DECIMALS = 1;

/** Separator between a player's position and NFL team, so `QB · KC` reads as one line. */
const META_SEPARATOR = " · ";

/** Shown when a team has a card but no roster rows behind it yet. */
export const EMPTY_ROSTER_LABEL =
  "No roster rows yet — waiting for the first sync.";

interface PlayerRowProps {
  player: RosterPlayer;
  isHighlighted: boolean;
}

/**
 * One roster line. Memoised because a board of twelve open cards re-renders on every realtime
 * invalidation, and the row objects are passed through by reference by `groupRosterBySlot`.
 */
const PlayerRow = memo(function PlayerRow({
  player,
  isHighlighted,
}: PlayerRowProps) {
  // A placeholder row for a player missing from the directory carries neither, so the whole
  // meta span is dropped rather than rendering a bare separator.
  const meta = [player.position, player.nflTeam]
    .filter(Boolean)
    .join(META_SEPARATOR);
  return (
    <li
      // The marker a search match leaves on the row, asserted on instead of the utility classes
      // so restyling the highlight does not have to mean rewriting the test.
      data-highlighted={isHighlighted || undefined}
      className={cn(
        "flex items-baseline justify-between gap-2 py-0.5 text-sm",
        isHighlighted && "rounded bg-accent px-1 text-accent-foreground",
      )}
    >
      <span className="min-w-0 truncate">
        <span className="font-medium">{player.fullName}</span>
        {meta === "" ? null : (
          <span className="ml-2 text-muted-foreground">{meta}</span>
        )}
      </span>
      <span className="shrink-0 tabular-nums text-muted-foreground">
        {player.projectedPoints === null
          ? NO_PROJECTION_TEXT
          : player.projectedPoints.toFixed(PLAYER_PROJECTION_DECIMALS)}
      </span>
    </li>
  );
});

/** What an unfilled lineup slot reads as, after its slot name: `FLEX — Empty`. */
const EMPTY_SLOT_SUFFIX = "Empty";

/** The one spelling of an empty row's text, so the panel and its tests cannot drift apart. */
function emptySlotText(position: string): string {
  return `${position} — ${EMPTY_SLOT_SUFFIX}`;
}

/**
 * A lineup slot nobody is starting in. Rendered in the warning token rather than the muted one
 * because this is not an absence to skim past: an unfilled FLEX is points the team is not
 * scoring, and Ben asked for it to be visible on the roster.
 */
const EmptySlotRow = memo(function EmptySlotRow({
  position,
}: {
  position: string;
}) {
  return (
    <li
      // The state's stable handle, so restyling the warning does not mean rewriting the test.
      data-empty-slot="true"
      className="flex items-baseline justify-between gap-2 py-0.5 text-sm text-destructive"
    >
      <span className="flex min-w-0 items-baseline gap-1.5 truncate font-medium">
        <AlertTriangle
          aria-hidden="true"
          className="h-3.5 w-3.5 shrink-0 self-center"
        />
        <span className="truncate">{emptySlotText(position)}</span>
      </span>
    </li>
  );
});

interface RosterPanelProps {
  players: RosterPlayer[];
  /**
   * The lineup, one row per slot in `seasons.roster_positions` order, empties included. The
   * starters section renders from this rather than from `players`, which is the whole point:
   * a slot with nobody in it has no player row to render and has to come from the layout.
   */
  starterSlots: StarterSlotRow[];
  highlightedPlayerIds: ReadonlySet<string>;
}

/**
 * The expanded card's roster: the lineup `layoutStarters` laid out, then the slot sections
 * `groupRosterBySlot` defines for everyone who is not starting. Ordering, grouping and the
 * lineup layout all live in the derivations, so this component only decides how a row looks.
 */
export function RosterPanel({
  players,
  starterSlots,
  highlightedPlayerIds,
}: RosterPanelProps) {
  // The slot labels are section names inside a card, not document structure, so they are plain
  // label elements wired to their list with `aria-labelledby` rather than headings — a dozen
  // cards' worth of <h4>s would otherwise flood the page's heading outline with `Bench`.
  const labelId = useId();

  if (players.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">{EMPTY_ROSTER_LABEL}</p>
    );
  }

  return (
    <div className="space-y-3">
      {/*
        The lineup, from the layout rather than from the roster rows. Every starter reaches it —
        `layoutStarters` appends the ones it cannot place — so the groups below drop their own
        starter section rather than rendering those players a second time.
      */}
      {starterSlots.length === 0 ? null : (
        <div>
          <p
            id={`${labelId}starter`}
            className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground"
          >
            {SLOT_LABELS.starter}
          </p>
          <ul aria-labelledby={`${labelId}starter`}>
            {starterSlots.map((row, index) =>
              row.kind === "filled" ? (
                <PlayerRow
                  key={row.player.sleeperPlayerId}
                  player={row.player}
                  isHighlighted={highlightedPlayerIds.has(
                    row.player.sleeperPlayerId,
                  )}
                />
              ) : (
                // Two empty slots can carry the same name (`RB`, `RB`), so the index is part
                // of the key: the position alone is not unique within one lineup.
                <EmptySlotRow
                  key={`${row.position}-${index}`}
                  position={row.position}
                />
              ),
            )}
          </ul>
        </div>
      )}

      {groupRosterBySlot(players)
        .filter((group) => group.slot !== "starter")
        .map((group) => (
          <div key={group.slot}>
            <p
              id={`${labelId}${group.slot}`}
              className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground"
            >
              {group.label}
            </p>
            <ul aria-labelledby={`${labelId}${group.slot}`}>
              {group.players.map((player) => (
                <PlayerRow
                  key={player.sleeperPlayerId}
                  player={player}
                  isHighlighted={highlightedPlayerIds.has(
                    player.sleeperPlayerId,
                  )}
                />
              ))}
            </ul>
          </div>
        ))}
    </div>
  );
}
