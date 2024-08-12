import { SquareArrowOutUpRight } from "lucide-react";
import { Link } from "react-router-dom";

import { RosterTable } from "@/components/roster-table/RosterTable";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export const RosterCard = () => {
  return (
    <Card className="overflow-hidden" x-chunk="dashboard-05-chunk-4">
      <CardHeader className="flex flex-row items-start bg-muted/50">
        <div className="grid gap-0.5">
          <CardTitle className="group flex items-center gap-2 text-lg">
            League Rosters
          </CardTitle>
        </div>
        <div className="ml-auto flex items-center gap-1">
          <Link
            to={"/rosters"}
            className={cn(
              buttonVariants({ variant: "outline" }),
              "h-8 gap-1 text-foreground/80",
            )}
          >
            <SquareArrowOutUpRight className="h-4" />
          </Link>
        </div>
      </CardHeader>
      <CardContent className="p-6 text-sm">
        <RosterTable type="compact" />
      </CardContent>
    </Card>
  );
};
