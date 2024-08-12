import { Axe, Home, Notebook, Trophy, Users } from "lucide-react";
import { Link, useLocation } from "react-router-dom";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const navItems = [
  {
    icon: Home,
    label: "Overview",
    to: `/`,
  },
  {
    icon: Users,
    label: "Rosters",
    to: `/rosters`,
  },
  {
    icon: Notebook,
    label: "Rules",
    to: `/rules`,
  },
  {
    icon: Trophy,
    label: "History",
    to: `/history`,
  },
];

export const Nav = () => {
  const location = useLocation();

  return (
    <aside className="fixed inset-y-0 left-0 z-10 hidden w-14 flex-col border-r bg-background sm:flex">
      <nav className="flex flex-col items-center gap-4 px-2 sm:py-5">
        <div className="group flex h-9 w-9 shrink-0 items-center justify-center gap-2 rounded-full bg-primary text-lg font-semibold text-primary-foreground md:h-8 md:w-8 md:text-base">
          <Axe className="h-4 w-4 transition-all group-hover:scale-110" />
          <span className="sr-only">Ultimate Guillotine</span>
        </div>
        {navItems.map((item) => {
          const isSelected = location.pathname === item.to;

          return (
            <Tooltip key={item.to}>
              <TooltipTrigger asChild>
                <Link
                  to={item.to}
                  className={cn(
                    "flex h-9 w-9 items-center justify-center rounded-lg   text-muted-foreground transition-colors hover:text-foreground md:h-8 md:w-8",
                    isSelected && "bg-accent text-accent-foreground",
                  )}
                >
                  <item.icon className="h-5 w-5" />
                  <span className="sr-only">{item.label}</span>
                </Link>
              </TooltipTrigger>
              <TooltipContent side="right">{item.label}</TooltipContent>
            </Tooltip>
          );
        })}
      </nav>
      {/* <nav className="mt-auto flex flex-col items-center gap-4 px-2 sm:py-5">
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:text-foreground md:h-8 md:w-8">
              <>
                <Settings className="h-5 w-5" />
                <span className="sr-only">Settings</span>
              </>
            </div>
          </TooltipTrigger>
          <TooltipContent side="right">Settings</TooltipContent>
        </Tooltip>
      </nav> */}
    </aside>
  );
};
