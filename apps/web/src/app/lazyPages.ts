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

export const HistoryPage = lazy(() =>
  import("@/app/history/HistoryPage").then((module) => ({
    default: module.HistoryPage,
  })),
);
