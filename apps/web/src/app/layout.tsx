import { Suspense, useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router";

import { prefetchPages } from "@/app/lazyPages";
import { BoardSkeleton } from "@/board/components/BoardStates";
import { HistoryListSkeleton } from "@/history/components/HistorySkeleton";
import { TradesPageSkeleton } from "@/history/components/TradesSkeleton";
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

/**
 * How long the shell gives the browser to find an idle moment for the prefetch before doing it
 * anyway, and the plain delay it falls back to where there is no idle callback at all. Both sit
 * past the opening curtain and the board's first reads, which is the point: the chunks cost the
 * board's first paint nothing.
 */
const PREFETCH_IDLE_TIMEOUT_MS = 3000;
const PREFETCH_DELAY_MS = 2500;

/**
 * What the Suspense boundary below shows while a page's chunk is on its way: the destination's
 * own loading state, so the shell says what is coming rather than showing a generic block, and
 * the page's own skeleton takes over from it without anything moving.
 */
function PageFallback({ pathname }: { pathname: string }) {
  if (pathname.startsWith("/trades")) return <TradesPageSkeleton />;
  if (pathname.startsWith("/history")) return <HistoryListSkeleton />;
  return <BoardSkeleton />;
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
 * The outlet sits inside one Suspense boundary, keyed by the path: the trades and history
 * pages arrive in their own chunks (`lazyPages.ts`), and a navigation is a transition, inside
 * which React keeps an already-shown boundary's old content on screen while the new content's
 * chunk is fetched. That is what made a tap on a tab look like nothing had happened (Ben,
 * 2026-09-10: "the ui just freezes when switching between things"). A new key is a new
 * boundary with nothing to keep, so the destination's loading state shows the moment the tab is
 * taken. The chunks are also prefetched once the browser is idle, so in practice the loading
 * state is seen only on a slow connection.
 */
function App() {
  const { pathname } = useLocation();

  useEffect(() => {
    if (typeof window.requestIdleCallback === "function") {
      const handle = window.requestIdleCallback(() => prefetchPages(), {
        timeout: PREFETCH_IDLE_TIMEOUT_MS,
      });
      return () => window.cancelIdleCallback(handle);
    }
    const timer = window.setTimeout(() => prefetchPages(), PREFETCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, []);

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
        <Suspense
          key={pathname}
          fallback={<PageFallback pathname={pathname} />}
        >
          <Outlet />
        </Suspense>
      </div>
    </div>
  );
}

export default App;
