import { useMemo } from "react";
import { Swords } from "lucide-react";

import { getOwnerByRosterId } from "@/components/roster-table/getOwnerByRosterId";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useLeagueRosters } from "@/queries/useLeagueRosters";

import { CURRENT_WEEK } from "../constants";
import { getCurrentGulag } from "./getCurrentGulag";

const SkeletonCard = () => (
  <Card>
    <CardHeader className="pb-2">
      <Skeleton className="h-4 w-[150px]" />
      <Skeleton className="h-8 w-[200px]" />
    </CardHeader>
    <CardContent>
      <Skeleton className="h-4 w-[100px]" />
    </CardContent>
  </Card>
);

export const HeaderAnalytics = () => {
  const currentGulag = getCurrentGulag(CURRENT_WEEK);
  const emptyGulag = currentGulag.length === 0;
  const { data: rosters, isLoading } = useLeagueRosters();

  const { highestScoring, lowestScoring } = useMemo(() => {
    if (!rosters) return { highestScoring: null, lowestScoring: null };

    const sortedRosters = rosters
      .filter((roster) => roster.roster_id !== 18)
      .sort((a, b) => b.settings.fpts - a.settings.fpts);

    return {
      highestScoring: sortedRosters[0],
      lowestScoring: sortedRosters[sortedRosters.length - 1],
    };
  }, [rosters]);

  if (isLoading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4">
      <Card className="sm:col-span-2" x-chunk="dashboard-05-chunk-1">
        <CardHeader className="pb-2">
          <CardDescription>Week {CURRENT_WEEK} Gulag </CardDescription>
          <CardTitle className="flex flex-wrap text-4xl">
            {emptyGulag ? (
              "No Participants"
            ) : (
              <>
                {currentGulag.map((team, i) => {
                  const isLast = i === currentGulag.length - 1;
                  return (
                    <div className="flex items-center" key={i}>
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
      {highestScoring && (
        <Card x-chunk="dashboard-05-chunk-2" className="hidden sm:block">
          <CardHeader className="pb-2">
            <CardDescription>Highest Scoring</CardDescription>
            <CardTitle className="text-4xl">
              {highestScoring.settings.fpts.toFixed(2)}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-xs text-muted-foreground">
              {getOwnerByRosterId(highestScoring.roster_id)?.name}
            </div>
          </CardContent>
        </Card>
      )}
      {lowestScoring && (
        <Card x-chunk="dashboard-05-chunk-3" className="hidden sm:block">
          <CardHeader className="pb-2">
            <CardDescription>Lowest Scoring</CardDescription>
            <CardTitle className="text-4xl">
              {lowestScoring.settings.fpts.toFixed(2)}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-xs text-muted-foreground">
              {getOwnerByRosterId(lowestScoring.roster_id)?.name}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};
