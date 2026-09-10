import { createBrowserRouter, redirect, RouteObject } from "react-router";

import { BoardPage } from "@/app/board/BoardPage";
import ErrorPage from "@/app/error-page";
import App from "@/app/layout";
// The trades and history pages arrive in their own chunks; `lazyPages.ts` says why the board
// does not.
import { HistoryPage, TradesPage } from "@/app/lazyPages";

/**
 * Ben's decision 1: the board is the home page. Everything else is a redirect onto it.
 *
 * The redirects are route loaders rather than a `<Navigate>` component, for two reasons: a
 * loader runs before anything renders, so a shared link never paints a page it is about to
 * leave; and defining a redirect component in this file would trip
 * `react-refresh/only-export-components`, since the file also exports the router itself.
 */
function redirectHome(request: Request): Response {
  // The board was reviewed at `/board` and members have shared `/board?sort=faab` links, so the
  // query string rides along and the sort they shared survives the hop.
  return redirect(`/${new URL(request.url).search}`);
}

export const router = createBrowserRouter([
  {
    path: "/",
    Component: App,
    ErrorBoundary: ErrorPage,
    children: [
      {
        path: "",
        element: <BoardPage />,
      },
      {
        path: "board",
        loader: ({ request }) => redirectHome(request),
      },
      {
        path: "trades",
        element: <TradesPage />,
      },
      {
        path: "history",
        element: <HistoryPage />,
      },
      // The catch-all stays last: it matches every path, and reading it after the pages it
      // is a fallback for is how the file says which routes are real.
      {
        path: "*",
        loader: () => redirect("/"),
      },
    ],
  },
] satisfies RouteObject[]);
