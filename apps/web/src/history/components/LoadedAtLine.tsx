import { useEffect, useState } from "react";

import { formatUpdatedAt } from "@/board/derive/time";

/**
 * How often the line re-reads the clock. The history tables change a handful of times a year,
 * so the text moves by the minute at most; a minute is also the finest step `formatUpdatedAt`
 * shows past the first one.
 */
const REFRESH_MS = 60_000;

/**
 * The "Updated …" footer `/trades` and `/history` share. `formatUpdatedAt` needs the instant it
 * compares against, and a component cannot read the clock during render, so the line keeps its
 * own — the same shape as the board header's per-second tick, scoped to this one paragraph so
 * the page above it never re-renders for it.
 */
export function LoadedAtLine({ loadedAt }: { loadedAt: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <p className="text-xs text-muted-foreground">
      {formatUpdatedAt(loadedAt, now)}
    </p>
  );
}
