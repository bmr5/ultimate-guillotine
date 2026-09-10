import { LoadingState } from "@/components/loading-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { REVEAL_CLASS, revealStyle } from "@/motion/reveal";

import { MS_PER_SECOND } from "../derive/time";
import { BOARD_GRID } from "../layout";
import { REALTIME_POLL_MS } from "../realtime";
import type { BoardQueryError } from "../useBoardData";

/** Placeholder cards shown before the first board payload resolves. */
const SKELETON_CARD_COUNT = 6;

/**
 * Where everything under the header sits in the page's cascade: the header is place `0`, and
 * the banner, the errors, the empty state and the first card all follow it as place `1`.
 */
const BELOW_HEADER = 1;

/**
 * The banner's wording quotes the poll it is describing, so the sentence cannot drift away from
 * the interval the page actually asks `useBoardData` for.
 */
const POLL_SECONDS = REALTIME_POLL_MS / MS_PER_SECOND;

export const REALTIME_PAUSED_TEXT = `Live updates are paused. Polling every ${POLL_SECONDS} seconds.`;

/** What the board says while its first payload is on its way; also the status region's name. */
export const BOARD_LOADING_LABEL = "Loading the board";

/**
 * The list's stand-in before the first board payload resolves: the sentence, then card-shaped
 * placeholders in the board's own grid. The placeholders are hidden from assistive technology —
 * the status line says everything they do. The sentence is the one thing on the site that
 * skips the cascade: it is the acknowledgement of a tap, and it has to be there at once.
 */
export function BoardSkeleton() {
  return (
    <div className="space-y-3">
      <LoadingState label={BOARD_LOADING_LABEL} />
      <ul aria-hidden="true" className={BOARD_GRID}>
        {Array.from({ length: SKELETON_CARD_COUNT }, (_, index) => index).map(
          (index) => (
            <li
              key={index}
              className={REVEAL_CLASS}
              style={revealStyle(BELOW_HEADER + 1 + index)}
            >
              <Card>
                <CardContent className="space-y-2 p-4">
                  <Skeleton className="h-4 w-1/2" />
                  <Skeleton className="h-3 w-2/3" />
                  <Skeleton className="h-3 w-1/3" />
                </CardContent>
              </Card>
            </li>
          ),
        )}
      </ul>
    </div>
  );
}

/**
 * Reached whenever the board has no teams and nothing failed — which includes the case where
 * `nfl_state` is empty, so the season never resolves and every query below it stays disabled.
 * That is genuinely "nothing has been synced yet", not an error, and it must not spin forever.
 */
export function BoardEmpty() {
  return (
    <Card className={REVEAL_CLASS} style={revealStyle(BELOW_HEADER)}>
      <CardContent className="p-6">
        <p className="font-medium">Waiting for the first sync</p>
        <p className="mt-1 text-sm text-muted-foreground">
          No teams have been written to Supabase yet. The board fills in as soon
          as the sync job runs.
        </p>
      </CardContent>
    </Card>
  );
}

/**
 * One alert per failed section, named so a reader can tell a dead projection run from a dead
 * roster fetch. The rest of the board keeps rendering behind them.
 */
export function BoardErrors({
  errors,
  onRetry,
}: {
  errors: BoardQueryError[];
  onRetry: () => void;
}) {
  if (errors.length === 0) {
    return null;
  }
  return (
    <div
      className={`space-y-2 ${REVEAL_CLASS}`}
      style={revealStyle(BELOW_HEADER)}
    >
      {errors.map((error) => (
        <Alert key={error.section} variant="destructive">
          <AlertTitle>{error.section} could not load</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-3">
            <span>{error.message}</span>
            <Button size="sm" variant="outline" onClick={onRetry}>
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      ))}
    </div>
  );
}

/**
 * Shown while the Realtime socket is down. `onRefresh` is the realtime hook's `refreshNow`, not
 * a plain refetch: the point of the button is to skip a pending backoff timer that may be most
 * of half a minute away, which only rebuilding the channel does.
 */
export function RealtimeBanner({ onRefresh }: { onRefresh: () => void }) {
  return (
    <div
      className={`flex flex-wrap items-center gap-3 rounded-md border bg-card px-3 py-2 text-sm text-muted-foreground ${REVEAL_CLASS}`}
      style={revealStyle(BELOW_HEADER)}
    >
      <span>{REALTIME_PAUSED_TEXT}</span>
      <Button size="sm" variant="outline" onClick={onRefresh}>
        Refresh now
      </Button>
    </div>
  );
}

/**
 * The rule between the survivors and the cut. `revealIndex` is its place in the cascade — the
 * page hands it the place after the last active card, so it settles in with the list rather
 * than ahead of it.
 */
export function EliminatedDivider({
  count,
  revealIndex,
}: {
  count: number;
  revealIndex: number;
}) {
  return (
    <h2
      className={`mt-8 border-t border-destructive/60 pt-3 text-sm font-medium text-muted-foreground ${REVEAL_CLASS}`}
      style={revealStyle(revealIndex)}
    >
      Eliminated ({count})
    </h2>
  );
}
