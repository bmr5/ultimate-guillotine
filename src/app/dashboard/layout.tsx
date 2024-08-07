import { useAutoAnimate } from "@formkit/auto-animate/react";
import { Outlet } from "react-router-dom";

import { cn } from "@/lib/utils";

import { DashboardNav } from "./dashboard-nav";

interface Props extends React.HTMLAttributes<HTMLDivElement> {
  orientation?: "vertical" | "horizontal";
}

export default function Dashboard({ className, ...props }: Props) {
  const [parent] = useAutoAnimate();

  return (
    <div
      ref={parent}
      className={cn(
        "grid h-display w-display grid-cols-[auto_1fr] overflow-hidden",
        className,
      )}
      {...props}
    >
      <DashboardNav />

      <Outlet />
    </div>
  );
}
