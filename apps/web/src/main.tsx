import React from "react";
import ReactDOM from "react-dom/client";

import "./globals.css";

import { RouterProvider } from "react-router-dom";

import { ThemeProvider } from "@/components/theme-provider";

import { PlayerDataProvider } from "./app/PlayerDataContext.tsx";
import { TailwindIndicator } from "./components/tailwind-indicator.tsx";
import { TooltipProvider } from "./components/ui/tooltip.tsx";
import { QueryProvider } from "./QueryProvider.tsx";
import { router } from "./router.tsx";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider defaultTheme="dark" storageKey="vite-ui-theme">
      <QueryProvider>
        <TailwindIndicator />
        <TooltipProvider delayDuration={200}>
          <PlayerDataProvider>
            <RouterProvider router={router} />
          </PlayerDataProvider>
        </TooltipProvider>
      </QueryProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
