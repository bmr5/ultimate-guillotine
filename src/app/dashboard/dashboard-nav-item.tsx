import { Link, LinkProps, useMatch } from "react-router-dom";

import { Icons } from "@/components/icons";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ValueOf } from "@/lib/type-helpers";
import { cn } from "@/lib/utils";

export interface DashboardNavItem extends LinkProps {
  name: string;
  Icon: ValueOf<typeof Icons>;
}

interface Props extends DashboardNavItem {}

export function DashboardNavItem({ name, Icon, to, ...props }: Props) {
  const current = useMatch(to.toString());

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Link
          to={to}
          className={cn(
            current
              ? "bg-background/20 text-white"
              : "text-background/70 hover:bg-background/10 hover:text-background/90",
            "inline-flex h-14 w-14 flex-shrink-0 cursor-pointer items-center justify-center rounded-lg transition-colors duration-200 ease-in-out",
          )}
          {...props}
        >
          <span className="sr-only">{name}</span>
          <Icon className="h-[26px] w-[26px]" aria-hidden="true" />
        </Link>
      </TooltipTrigger>
      <TooltipContent side="right" sideOffset={6} align="start">
        {name}
      </TooltipContent>
    </Tooltip>
  );
}
