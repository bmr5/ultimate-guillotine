import { Suspense } from "react";
import { NavLink, Outlet } from "react-router";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { REVEAL_CLASS, revealStyle } from "@/motion/reveal";

/**
 * The three public pages, in the order Ben asked for them.
 *
 * `end` on `/` keeps the board link from matching every route: without it `NavLink` treats `/`
 * as a prefix of `/trades` and marks the board current on all three pages.
 */
const LINKS: [to: string, label: string, end: boolean][] = [
  ["/", "Board", true],
  ["/trades", "Trades", false],
  ["/history", "History", false],
];

/** What the outlet says while a page's chunk is on its way; also the placeholder's name. */
export const PAGE_FALLBACK_LABEL = "Loading the page";

/** The placeholder's rows: a header strip and three cards, the shape every page shares. */
const PAGE_FALLBACK_ROWS = ["h-28", "h-32", "h-32", "h-32"];

/**
 * Shown by the Suspense boundary below while a lazily loaded page (`router.tsx`) is still on its
 * way. Each row is wrapped rather than given the cascade class itself: `Skeleton` already
 * animates (its pulse), and one element cannot run both.
 */
function PageFallback() {
  return (
    <div role="status" aria-label={PAGE_FALLBACK_LABEL} className="space-y-3">
      {PAGE_FALLBACK_ROWS.map((height, index) => (
        <div key={index} className={REVEAL_CLASS} style={revealStyle(index)}>
          <Skeleton className={cn("w-full rounded-xl", height)} />
        </div>
      ))}
    </div>
  );
}

/**
 * The shell is the wordmark and the nav, sitting on the sky with no bar and no border of their
 * own — the board carries its own header below, and that is the one frosted surface.
 * The site is dark only, so there is no theme toggle here any more.
 *
 * `NavLink` writes `aria-current="page"` on the active link itself, so the marking a screen
 * reader announces and the styling below always agree: the current page is set in ink with an
 * ember rule beneath it, the others in ash.
 *
 * The outlet sits inside one Suspense boundary: the trades and history pages arrive in their
 * own chunks, and the boundary is what shows the placeholder rather than an empty outlet while
 * one is fetched. Navigations are transitions, so moving between pages keeps the old page on
 * screen until the new one is ready; the placeholder is only ever seen on a cold load.
 */
function App() {
  return (
    <div className="min-h-screen w-full">
      <div className="mx-auto w-full max-w-6xl px-4 py-5">
        <header className={REVEAL_CLASS} style={revealStyle(0)}>
          <h1 className="mb-1 text-2xl leading-none figures">
            Ultimate Guillotine
          </h1>
          <nav aria-label="Pages" className="mb-4 flex gap-5 text-sm">
            {LINKS.map(([to, label, end]) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cn(
                    "rounded-sm py-1 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    isActive
                      ? "border-b-2 border-primary font-medium text-foreground"
                      : "border-b-2 border-transparent text-muted-foreground hover:text-foreground",
                  )
                }
              >
                {label}
              </NavLink>
            ))}
          </nav>
        </header>
        <Suspense fallback={<PageFallback />}>
          <Outlet />
        </Suspense>
      </div>
    </div>
  );
}

export default App;
