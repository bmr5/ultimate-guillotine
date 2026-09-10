import { LoadingState } from "@/components/loading-state";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { REVEAL_CLASS, revealStyle } from "@/motion/reveal";

import { CARD_GRID, SEASON_CARD_PLACEHOLDER_HEIGHT_CLASS } from "../layout";

/** What the page says while the seasons are on their way; also the status region's name. */
export const SEASONS_LOADING_LABEL = "Loading seasons";

/** Enough card-shaped blocks to fill a phone screen; more would only scroll. */
const PLACEHOLDER_CARD_COUNT = 6;

/**
 * The history page's stand-in while the seasons load, and the shell's while the page's chunk is
 * on its way (`app/layout.tsx`): the sentence, then card-shaped blocks in the card grid, each the
 * size of the season card it is waiting for. The blocks are hidden from assistive technology —
 * the status line says everything they do. The sentence skips the cascade the blocks ride: it
 * is the acknowledgement of a tap on the tab, and it has to be there at once.
 */
export function HistoryListSkeleton() {
  return (
    <div className="space-y-2">
      <LoadingState label={SEASONS_LOADING_LABEL} />
      <ul aria-hidden="true" className={CARD_GRID}>
        {Array.from({ length: PLACEHOLDER_CARD_COUNT }, (_, index) => (
          <li
            key={index}
            className={REVEAL_CLASS}
            style={revealStyle(1 + index)}
          >
            <Skeleton
              className={cn(
                "w-full rounded-xl",
                SEASON_CARD_PLACEHOLDER_HEIGHT_CLASS,
              )}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}
