import { createBrowserRouter, RouteObject } from "react-router-dom";

import ErrorPage from "@/app/error-page";
import App from "@/app/layout";

import HomePage from "./app/home-page/HomePage";

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
        path: "rules",
        element: <div>Rules</div>,
      },
    ],
  },
] satisfies RouteObject[]);
