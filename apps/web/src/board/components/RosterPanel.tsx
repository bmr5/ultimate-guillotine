import { memo } from "react";

import { cn } from "@/lib/utils";

import { groupRosterBySlot } from "../derive/roster";
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

interface RosterPanelProps {
  players: RosterPlayer[];
  highlightedPlayerIds: ReadonlySet<string>;
}

/**
 * The expanded card's roster, cut into the slot sections `groupRosterBySlot` defines. Ordering
 * and grouping live in the derivation, so this component only decides how a row looks.
 */
export function RosterPanel({
  players,
  highlightedPlayerIds,
}: RosterPanelProps) {
  if (players.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">{EMPTY_ROSTER_LABEL}</p>
    );
  }

  return (
    <div className="space-y-3">
      {groupRosterBySlot(players).map((group) => (
        <div key={group.slot}>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {group.label}
          </h4>
          <ul>
            {group.players.map((player) => (
              <PlayerRow
                key={player.sleeperPlayerId}
                player={player}
                isHighlighted={highlightedPlayerIds.has(player.sleeperPlayerId)}
              />
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
