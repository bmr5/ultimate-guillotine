import { NavLink } from "react-router";

import { cn } from "@/lib/utils";

export function HistoryTabs() {
  return (
    <nav aria-label="History sections" className="flex gap-2 text-sm">
      {[
        ["/history/2026", "2026 season"],
        ["/history", "Past champions"],
      ].map(([to, label]) => (
        <NavLink
          key={to}
          to={to}
          end
          className={({ isActive }) =>
            cn(
              "rounded-lg border px-4 py-2 outline-none focus-visible:ring-2 focus-visible:ring-ring",
              isActive
                ? "border-primary/40 bg-primary/10 text-primary"
                : "bg-card text-muted-foreground hover:text-foreground",
            )
          }
        >
          {label}
        </NavLink>
      ))}
    </nav>
  );
}
