import React from "react";
import ReactDOM from "react-dom/client";

import "./globals.css";

import { RouterProvider } from "react-router/dom";

import { TailwindIndicator } from "./components/tailwind-indicator.tsx";
import { TooltipProvider } from "./components/ui/tooltip.tsx";
import { QueryProvider } from "./QueryProvider.tsx";
import { router } from "./router.tsx";
import { Sky } from "./sky/Sky.tsx";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Sky />
    <QueryProvider>
      <TailwindIndicator />
      <TooltipProvider delayDuration={200}>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryProvider>
  </React.StrictMode>,
);
