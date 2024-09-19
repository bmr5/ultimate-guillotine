import { Swords } from "lucide-react";

import { getOwnerByRosterId } from "@/components/roster-table/getOwnerByRosterId";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useLeagueRosters } from "@/queries/useLeagueRosters";

import { CURRENT_WEEK } from "../constants";
import { getCurrentGulag } from "./getCurrentGulag";

export const HeaderAnalytics = () => {
  const currentGulag = getCurrentGulag(CURRENT_WEEK);
  const emptyGulag = currentGulag.length === 0;
  const { data: rosters } = useLeagueRosters();

  // sort the rosters by fpts
  const sortedRosters = (rosters ?? []).sort(
    (a, b) => b.settings.fpts - a.settings.fpts,
  );

  return (
    <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4">
      <Card className="sm:col-span-2" x-chunk="dashboard-05-chunk-1">
        <CardHeader className="pb-2">
          <CardDescription>Week {CURRENT_WEEK} Gulag </CardDescription>
          <CardTitle className="flex flex-wrap text-4xl">
            {emptyGulag ? (
              "No Particants"
            ) : (
              <>
                {currentGulag.map((team, i) => {
                  const isLast = i === currentGulag.length - 1;
                  return (
                    <div className="flex items-center">
                      <div key={team.id} className="text-2xl">
                        {team.name}
                      </div>
                      {!isLast && <Swords className="mx-2 text-2xl" />}
                    </div>
                  );
                })}
              </>
            )}
          </CardTitle>
        </CardHeader>
      </Card>
      <Card x-chunk="dashboard-05-chunk-2" className="hidden sm:block">
        <CardHeader className="pb-2">
          <CardDescription>Highest Scoring</CardDescription>
          <CardTitle className="text-4xl">
            {sortedRosters[0].settings.fpts}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-xs text-muted-foreground">
            {getOwnerByRosterId(sortedRosters[0].roster_id)?.name}
          </div>
        </CardContent>
      </Card>
      <Card x-chunk="dashboard-05-chunk-3" className="hidden sm:block">
        <CardHeader className="pb-2">
          <CardDescription>Lowest Scoring</CardDescription>
          <CardTitle className="text-4xl">
            {sortedRosters[sortedRosters.length - 2].settings.fpts}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-xs text-muted-foreground">
            {
              getOwnerByRosterId(
                sortedRosters[sortedRosters.length - 2].roster_id,
              )?.name
            }
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
