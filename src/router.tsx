import { createBrowserRouter, RouteObject } from "react-router-dom";

import ErrorPage from "@/app/error-page";
import App from "@/app/layout";

import { HistoryPage } from "./app/history/HistoryPage";
import HomePage from "./app/home/HomePage";
import { RostersPage } from "./app/rosters/RostersPage";
import { RulesPage } from "./app/rules/RulesPage";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: App,
    ErrorBoundary: ErrorPage,
    children: [
      {
        path: "",
        element: <HomePage />,
      },
      {
        path: "rosters",
        element: <RostersPage />,
      },
      {
        path: "rules",
        element: <RulesPage />,
      },
      {
        path: "history",
        element: <HistoryPage />,
      },
    ],
  },
] satisfies RouteObject[]);
