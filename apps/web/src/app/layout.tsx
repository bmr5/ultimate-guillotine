import { Outlet } from "react-router-dom";

import { ModeToggle } from "@/components/mode-toggle";

/**
 * The shell holds the league title and the light/dark toggle and nothing else. The nav pointed
 * at the pages Task 11 deletes, and the board carries its own sticky header, so a second bar of
 * chrome above it would only push the week and the sort controls down the screen.
 */
function App() {
  return (
    <div className="min-h-screen w-full bg-muted/40">
      <div className="mx-auto w-full max-w-6xl px-4 py-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h1 className="text-lg font-semibold">Ultimate Guillotine</h1>
          <ModeToggle />
        </div>
        <Outlet />
      </div>
    </div>
  );
}

export default App;
