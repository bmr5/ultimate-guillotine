import { LoadingState } from "@/components/loading-state";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { REVEAL_CLASS, revealStyle } from "@/motion/reveal";

import { CARD_GRID, TRADE_CARD_HEIGHT_CLASS } from "../layout";

/** What the page says while the catalog is on its way; also the status region's name. */
export const TRADES_LOADING_LABEL = "Loading trades";

/** Enough card-shaped blocks to fill a phone screen; more would only scroll. */
const PLACEHOLDER_CARD_COUNT = 4;

/**
 * The list's stand-in while the catalog loads: the sentence, then card-shaped blocks in the
 * card grid, each the size of the card it is waiting for, so nothing moves when the cards land.
 * The blocks are hidden from assistive technology — the status line says everything they do.
 * The sentence skips the cascade the blocks ride: it is the acknowledgement of a tap on the
 * tab, and it has to be there at once.
 *
 * `revealIndex` is where the list sits in the page's cascade (`src/motion/reveal.ts`); the page
 * counts it from below its strips.
 */
export function TradesListSkeleton({
  revealIndex = 0,
}: {
  revealIndex?: number;
}) {
  return (
    <div className="space-y-2">
      <LoadingState label={TRADES_LOADING_LABEL} />
      <ul aria-hidden="true" className={CARD_GRID}>
        {Array.from({ length: PLACEHOLDER_CARD_COUNT }, (_, index) => (
          <li
            key={index}
            className={REVEAL_CLASS}
            style={revealStyle(revealIndex + 1 + index)}
          >
            <Skeleton
              className={cn("w-full rounded-xl", TRADE_CARD_HEIGHT_CLASS)}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The whole page's stand-in while its chunk is on its way (`app/layout.tsx`): the filter bar and
 * the stats strip as blocks of their own height, then the list. The page swaps its real strips
 * in when it mounts and keeps the same list skeleton until its data lands.
 *
 * The two blocks skip the cascade, like the sentence below them: without that, the first frames
 * after a tap showed the sentence floating alone in the middle of an empty page while the
 * blocks above it were still fading in.
 */
export function TradesPageSkeleton() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-40 w-full rounded-xl" />
      <Skeleton className="h-20 w-full rounded-xl" />
      <TradesListSkeleton revealIndex={0} />
    </div>
  );
}
