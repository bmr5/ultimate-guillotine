import React from "react";
import ReactDOM from "react-dom/client";

import "./globals.css";

import { RouterProvider } from "react-router/dom";

import { TailwindIndicator } from "./components/tailwind-indicator.tsx";
import { TooltipProvider } from "./components/ui/tooltip.tsx";
import { IntroGate } from "./intro/IntroGate.tsx";
import { QueryProvider } from "./QueryProvider.tsx";
import { router } from "./router.tsx";
import { Sky } from "./sky/Sky.tsx";

/*
  The gate is the outermost thing so the opening curtain covers the sky as well as the page, and
  so the phase it carries (`data-intro`) is above every `.reveal` entrance on the site.
*/
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <IntroGate>
      <Sky />
      <QueryProvider>
        <TailwindIndicator />
        <TooltipProvider delayDuration={200}>
          <RouterProvider router={router} />
        </TooltipProvider>
      </QueryProvider>
    </IntroGate>
  </React.StrictMode>,
);
