import { cn } from "@/lib/utils";

import type { RosterPlayer } from "../types";
import { DraftedMark } from "./DraftedMark";

/** The ring every bare `<button>` on the board carries. */
const FOCUS_RING_CLASS =
  "ring-offset-background focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

export type PlayerNameSource = Pick<
  RosterPlayer,
  "sleeperPlayerId" | "fullName" | "draft" | "draftedHere"
>;

/**
 * A player's name as the one control that opens his card, with the drafted-here mark beside it.
 *
 * Shared by the roster panel and the position view so the mark and the tap live in one place.
 * Both are siblings inside a flex span — the mark is its own button and may not nest inside
 * the name's — and the name is the part that truncates.
 */
export function PlayerName({
  player,
  ownerName,
  onOpen,
  className,
}: {
  player: PlayerNameSource;
  ownerName: string;
  onOpen: (sleeperPlayerId: string) => void;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex min-w-0 items-center", className)}>
      <button
        type="button"
        aria-haspopup="dialog"
        onClick={() => onOpen(player.sleeperPlayerId)}
        // The 44px floor every control on the board keeps, with the negative margin the row's
        // badges use so the floor costs the line no height.
        className={cn(
          "-my-2 inline-flex min-h-[44px] min-w-0 items-center truncate rounded-sm text-left font-medium underline-offset-2 hover:underline",
          FOCUS_RING_CLASS,
        )}
      >
        {player.fullName}
      </button>
      {player.draftedHere && player.draft !== null ? (
        <DraftedMark ownerName={ownerName} amount={player.draft.amount} />
      ) : null}
    </span>
  );
}
