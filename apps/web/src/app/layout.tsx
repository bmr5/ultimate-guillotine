import { NavLink, Outlet } from "react-router";

import { cn } from "@/lib/utils";

/**
 * The three public pages, in the order Ben asked for them.
 *
 * `end` on `/` keeps the board link from matching every route: without it `NavLink` treats `/`
 * as a prefix of `/trades` and marks the board current on all three pages.
 */
const LINKS: [to: string, label: string, end: boolean][] = [
  ["/", "Board", true],
  ["/trades", "Trades", false],
  ["/history", "History", false],
];

/**
 * The shell is the wordmark and the nav, sitting on the sky with no bar and no border of their
 * own — the board carries its own header below, and that is the one frosted surface.
 * The site is dark only, so there is no theme toggle here any more.
 *
 * `NavLink` writes `aria-current="page"` on the active link itself, so the marking a screen
 * reader announces and the styling below always agree: the current page is set in ink with an
 * ember rule beneath it, the others in ash.
 */
function App() {
  return (
    <div className="min-h-screen w-full">
      <div className="mx-auto w-full max-w-6xl px-4 py-5">
        <h1 className="mb-1 text-2xl leading-none figures">
          Ultimate Guillotine
        </h1>
        <nav aria-label="Pages" className="mb-4 flex gap-5 text-sm">
          {LINKS.map(([to, label, end]) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "rounded-sm py-1 outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  isActive
                    ? "border-b-2 border-primary font-medium text-foreground"
                    : "border-b-2 border-transparent text-muted-foreground hover:text-foreground",
                )
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <Outlet />
      </div>
    </div>
  );
}

export default App;
