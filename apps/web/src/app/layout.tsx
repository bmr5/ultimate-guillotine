import { NavLink, Outlet } from "react-router";

import { ModeToggle } from "@/components/mode-toggle";
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
 * The shell holds the league title, the nav between the three public pages, and the light/dark
 * toggle. The board carries its own sticky header below this, so the bar stays one line high.
 *
 * `NavLink` writes `aria-current="page"` on the active link itself, so the marking a screen
 * reader announces and the styling below always agree.
 */
function App() {
  return (
    <div className="min-h-screen w-full bg-muted/40">
      <div className="mx-auto w-full max-w-6xl px-4 py-4">
        <div className="mb-2 flex items-center justify-between gap-3">
          <h1 className="text-lg font-semibold">Ultimate Guillotine</h1>
          <ModeToggle />
        </div>
        <nav aria-label="Pages" className="mb-3 flex gap-4 text-sm">
          {LINKS.map(([to, label, end]) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "hover:underline",
                  isActive ? "font-medium" : "text-muted-foreground",
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
