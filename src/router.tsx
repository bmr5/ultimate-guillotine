import {
  createBrowserRouter,
  LoaderFunctionArgs,
  redirect,
  RouteObject,
} from "react-router-dom";

import { Analytics } from "@/app/dashboard/analytics/page";
import Layout from "@/app/dashboard/layout";
import { DashHome } from "@/app/dashboard/page";
import { Settings } from "@/app/dashboard/settings/page";
import ErrorPage from "@/app/error-page";
import App from "@/app/layout";

import HomePage from "./app";
import { Icons } from "./components/icons";

// export const topLevelDashboardRoutes = [
//   {
//     id: "Home",
//     path: "/dashboard",
//     element: <DashHome />,
//     Icon: Icons.home,
//   },
//   {
//     id: "Analytics",
//     path: "/dashboard/analytics",
//     element: <Analytics />,
//     Icon: Icons.analytics,
//   },
//   {
//     id: "Settings",
//     path: "/dashboard/settings",
//     element: <Settings />,
//     Icon: Icons.settings,
//   },
// ];

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
      // {
      //   path: "login",
      //   // example of lazy loading a route
      //   lazy: () =>
      //     import("./app/login/page").then((module) => ({
      //       element: <module.LoginPage />,
      //     })),
      // },
      // {
      //   id: "Dashboard",
      //   path: "/dashboard",
      //   loader: protectedLoader,
      //   Component: Layout,
      //   children: topLevelDashboardRoutes,
      // },
    ],
  },
] satisfies RouteObject[]);

function protectedLoader({ request }: LoaderFunctionArgs) {
  const isAuthenticated = true;

  if (!isAuthenticated) {
    let params = new URLSearchParams();
    params.set("from", new URL(request.url).pathname);
    return redirect("/login?" + params.toString());
  }
  return null;
}
