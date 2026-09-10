import { memo, useId } from "react";
import { AlertTriangle } from "lucide-react";

import { cn } from "@/lib/utils";

import { injuryTag } from "../derive/availability";
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

/**
 * The word after a starter's two numbers: `12.4 / 14.1 proj`.
 *
 * Ben asked for the live score beside the projection on the card; a starter's row is where the
 * same question is asked one player at a time — who is carrying the number and who has not
 * played yet. Only starters get it: a bench player's live points are real but they are not part
 * of this week's total, and putting them on every row would bury the nine that are.
 */
const LIVE_POINTS_SEPARATOR = " / ";
const PROJECTION_SUFFIX = " proj";

/** Spoken forms, so a row is not read out as `12.4 slash 14.1 proj`. */
const LIVE_POINTS_LABEL = "scored";
const PROJECTION_LABEL = "projected";

/** Separator between a player's position and NFL team, so `QB · KC` reads as one line. */
const META_SEPARATOR = " · ";

/**
 * The injury tag, after the position and NFL team a reader already scans for.
 *
 * Ben's addendum: a starter who is out and a starter nobody has projected read identically on
 * the board. `Out`, `IR`, `Q`, `D` and the rest sit on the row itself so the reason is on the
 * roster, not only in the count on the collapsed card. The six unavailable statuses take the
 * warning token, because they are the ones that cost points this week; `Q` and `D` stay muted.
 *
 * The short tag is what shows; the full wording rides along as the native `title` a reader
 * hovers and as the visually hidden text a screen reader gets whether or not it is hovered.
 */
const InjuryTag = memo(function InjuryTag({
  status,
}: {
  status: string | null;
}) {
  const tag = injuryTag(status);
  if (tag === null) {
    return null;
  }
  return (
    <span
      // The state's stable handle: restyling the tag must not mean rewriting the test.
      data-injury={tag.status}
      title={tag.title}
      className={cn(
        "ml-1.5 rounded border px-1 text-[0.6875rem] font-medium",
        tag.isUnavailable
          ? "border-destructive/40 text-destructive"
          : "border-border text-muted-foreground",
      )}
    >
      <span aria-hidden="true">{tag.tag}</span>
      <span className="sr-only">{tag.title}</span>
    </span>
  );
});

/** Shown when a team has a card but no roster rows behind it yet. */
export const EMPTY_ROSTER_LABEL =
  "No roster rows yet — waiting for the first sync.";

interface PlayerRowProps {
  player: RosterPlayer;
  isHighlighted: boolean;
  /**
   * True for a row in the lineup. The live figure is a starter's alone — see
   * `LIVE_POINTS_SEPARATOR` — and the panel knows which rows those are because it renders them
   * from `starterSlots` rather than from `players`.
   */
  isStarter?: boolean;
}

/**
 * One roster line. Memoised because a board of twelve open cards re-renders on every realtime
 * invalidation, and the row objects are passed through by reference by `groupRosterBySlot`.
 */
const PlayerRow = memo(function PlayerRow({
  player,
  isHighlighted,
  isStarter = false,
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
        <InjuryTag status={player.injuryStatus} />
      </span>
      <span className="shrink-0 text-muted-foreground tabular-nums">
        {isStarter && player.livePoints !== null ? (
          <>
            {/*
              The live figure leads and takes the foreground; the projection follows, muted and
              labelled, so the pair reads as "this is what he has, that is what was expected".
              A starter who has not scored yet shows `0.0` in the muted token rather than being
              hidden — before kickoff that is every starter, and it is a fact, not an absence.
            */}
            <span
              data-live-points
              className={
                player.livePoints === 0
                  ? "text-muted-foreground"
                  : "text-foreground"
              }
            >
              <span aria-hidden="true">
                {player.livePoints.toFixed(PLAYER_PROJECTION_DECIMALS)}
              </span>
              <span className="sr-only">{`${LIVE_POINTS_LABEL} ${player.livePoints.toFixed(
                PLAYER_PROJECTION_DECIMALS,
              )}, `}</span>
            </span>
            <span aria-hidden="true">{LIVE_POINTS_SEPARATOR}</span>
            <span>
              <span aria-hidden="true">
                {player.projectedPoints === null
                  ? NO_PROJECTION_TEXT
                  : player.projectedPoints.toFixed(PLAYER_PROJECTION_DECIMALS)}
                {PROJECTION_SUFFIX}
              </span>
              <span className="sr-only">
                {player.projectedPoints === null
                  ? `no ${PROJECTION_LABEL}`
                  : `${PROJECTION_LABEL} ${player.projectedPoints.toFixed(
                      PLAYER_PROJECTION_DECIMALS,
                    )}`}
              </span>
            </span>
          </>
        ) : player.projectedPoints === null ? (
          NO_PROJECTION_TEXT
        ) : (
          player.projectedPoints.toFixed(PLAYER_PROJECTION_DECIMALS)
        )}
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
            className="mb-1 text-xs font-medium text-muted-foreground"
          >
            {SLOT_LABELS.starter}
          </p>
          <ul aria-labelledby={`${labelId}starter`}>
            {starterSlots.map((row, index) =>
              row.kind === "filled" ? (
                <PlayerRow
                  key={row.player.sleeperPlayerId}
                  player={row.player}
                  isStarter
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
              className="mb-1 text-xs font-medium text-muted-foreground"
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
