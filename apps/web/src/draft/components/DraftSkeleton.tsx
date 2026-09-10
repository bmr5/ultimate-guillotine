import { LoadingState } from "@/components/loading-state";
import { Skeleton } from "@/components/ui/skeleton";
import { REVEAL_CLASS, revealStyle } from "@/motion/reveal";

export const DRAFT_LOADING_LABEL = "Loading the draft";

const PLACEHOLDER_ROW_COUNT = 9;

/** The list's stand-in: the sentence, then row-shaped blocks hidden from assistive technology. */
export function DraftListSkeleton({
  revealIndex = 0,
}: {
  revealIndex?: number;
}) {
  return (
    <div className="space-y-2">
      <LoadingState label={DRAFT_LOADING_LABEL} />
      <ul aria-hidden="true" className="space-y-1">
        {Array.from({ length: PLACEHOLDER_ROW_COUNT }, (_, index) => (
          <li
            key={index}
            className={REVEAL_CLASS}
            style={revealStyle(revealIndex + 1 + index)}
          >
            <Skeleton className="h-10 w-full rounded-md" />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The whole page's stand-in while its chunk is on its way (`app/layout.tsx`). */
export function DraftPageSkeleton() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-20 w-full rounded-xl" />
      <DraftListSkeleton revealIndex={0} />
    </div>
  );
}
