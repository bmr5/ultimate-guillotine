import { Swords } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

import { CURRENT_WEEK } from "../constants";
import { getCurrentGulag } from "./getCurrentGulag";

export const HeaderAnalytics = () => {
  const currentGulag = getCurrentGulag(CURRENT_WEEK);
  return (
    <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-2 xl:grid-cols-4">
      <Card className="sm:col-span-2" x-chunk="dashboard-05-chunk-0">
        <CardHeader className="pb-2">
          <CardDescription>Current Gulag</CardDescription>
          <CardTitle className="flex flex-wrap text-4xl">
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
          </CardTitle>
        </CardHeader>
      </Card>
      <Card x-chunk="dashboard-05-chunk-1">
        <CardHeader className="pb-2">
          <CardDescription>Highest Scoring</CardDescription>
          <CardTitle className="text-4xl">1000</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-xs text-muted-foreground">
            Supreme Leader (Ben)
          </div>
        </CardContent>
      </Card>
      <Card x-chunk="dashboard-05-chunk-2">
        <CardHeader className="pb-2">
          <CardDescription>Worst Scoring</CardDescription>
          <CardTitle className="text-4xl">700</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-xs text-muted-foreground">
            Supreme Leader (Ben)
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
