import React from "react";
import ReactDOM from "react-dom/client";

import "./globals.css";

import { RouterProvider } from "react-router-dom";

import { ThemeProvider } from "@/components/theme-provider";

import { TailwindIndicator } from "./components/tailwind-indicator.tsx";
import { TooltipProvider } from "./components/ui/tooltip.tsx";
import { QueryProvider } from "./QueryProvider.tsx";
import { router } from "./router.tsx";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider defaultTheme="light" storageKey="vite-ui-theme">
      <QueryProvider>
        <TailwindIndicator />
        <TooltipProvider delayDuration={200}>
          <RouterProvider router={router} />
        </TooltipProvider>
      </QueryProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
