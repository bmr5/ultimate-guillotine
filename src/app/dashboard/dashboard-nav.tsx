import { ModeToggle } from "@/components/mode-toggle";
import { topLevelDashboardRoutes } from "@/router";

import { DashboardNavItem } from "./dashboard-nav-item";

export function DashboardNav() {
  return (
    <nav className="flex flex-col gap-3 bg-foreground px-3 py-6 font-semibold text-muted-foreground">
      <div className=" flex flex-grow flex-col space-y-3">
        {topLevelDashboardRoutes.map((route) => {
          return (
            <DashboardNavItem
              key={route.path}
              to={route.path}
              name={route.id}
              Icon={route.Icon}
            />
          );
        })}
      </div>
      {/* Bottom section of nav */}
      <div>
        <div className="inline-flex h-14 w-14 flex-shrink-0 cursor-pointer items-center justify-center rounded-lg transition-colors duration-200 ease-in-out">
          <ModeToggle />
        </div>
      </div>
    </nav>
  );
}
