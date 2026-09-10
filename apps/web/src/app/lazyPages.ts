import { lazy } from "react";

/**
 * The pages that arrive in their own chunks, resolved by the Suspense boundary in `layout.tsx`.
 *
 * The board is not among them: it is the home page and the reason the site exists, and loading
 * it lazily would put a round trip for its chunk in front of its first Supabase read. The other
 * two are visited a few times a season, and their code — the filter bar, the modal, the catalog
 * derivations — has no business in the board's first paint.
 *
 * A file of their own because `react-refresh/only-export-components` wants a module that
 * exports a component to export nothing else, and `router.tsx` exports the router. `lazy` wants
 * a default export; the pages are named exports, so the module is reshaped here rather than
 * the pages changed.
 */
export const TradesPage = lazy(() =>
  import("@/app/trades/TradesPage").then((module) => ({
    default: module.TradesPage,
  })),
);

export const DraftPage = lazy(() =>
  import("@/app/draft/DraftPage").then((module) => ({
    default: module.DraftPage,
  })),
);

export const HistoryPage = lazy(() =>
  import("@/app/history/HistoryPage").then((module) => ({
    default: module.HistoryPage,
  })),
);

/**
 * Fetches both chunks ahead of any tap on their tabs. The shell calls this once the browser is
 * idle after the board's first paint, so the chunks cost the board nothing and a tab opens at
 * once when it is taken — Ben, 2026-09-10: "it does feel like the ui just freezes when
 * switching between things", and the wait for a chunk was the freeze. The same specifiers as
 * above, so the bundler hands back the same chunks and `lazy` finds them already loaded. A
 * failed prefetch is nothing to report: the tab will simply fetch its chunk when taken.
 */
export function prefetchPages(): void {
  void import("@/app/trades/TradesPage").catch(() => undefined);
  void import("@/app/history/HistoryPage").catch(() => undefined);
  void import("@/app/draft/DraftPage").catch(() => undefined);
}
