import React from "react";

import { getOwnerByRosterId } from "@/components/roster-table/getOwnerByRosterId";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useLeagueGulagData } from "@/queries/useLeagueGulagData";

import { CURRENT_WEEK, owners } from "../constants";
import { generateLeagueStatusData } from "./generateLeagueStatusData";

export const MobileLeagueStatus = () => {
  const allGulagData = useLeagueGulagData();

  const data = React.useMemo(
    () => generateLeagueStatusData(owners, CURRENT_WEEK, allGulagData),
    [],
  );

  const sortedData = React.useMemo(() => {
    return [...data].sort((a, b) => b.week - a.week);
  }, [data]);

  return (
    <Card className="w-full">
      <CardHeader>
        <CardTitle>League Status</CardTitle>
      </CardHeader>
      <CardContent>
        <Accordion type="single" collapsible className="w-full">
          {sortedData.map((weekData) => (
            <AccordionItem key={weekData.week} value={`week-${weekData.week}`}>
              <AccordionTrigger className="text-lg font-semibold">
                Week {weekData.week}
              </AccordionTrigger>
              <AccordionContent>
                <div className="space-y-4">
                  <div>
                    <h4 className="mb-2 font-semibold">Gulag Teams</h4>
                    <div className="flex flex-wrap gap-1">
                      {weekData.gulagTeams.map((team) => (
                        <Badge key={team} className="bg-amber-300">
                          {getOwnerByRosterId(team)?.name}
                        </Badge>
                      ))}
                    </div>
                  </div>
                  <div>
                    <h4 className="mb-2 font-semibold">Gen Pool Teams</h4>
                    <div className="flex flex-wrap gap-1">
                      {weekData.genPoolTeams.map((team) => (
                        <Badge key={team} className="bg-green-300">
                          {getOwnerByRosterId(team)?.name}
                        </Badge>
                      ))}
                    </div>
                  </div>
                  <div>
                    <h4 className="mb-2 font-semibold">Teams Eliminated</h4>
                    <div className="flex flex-wrap gap-1">
                      {weekData.teamsEliminated.map((team) => {
                        const owner = getOwnerByRosterId(team);
                        const isEliminatedThisWeek =
                          owner?.eliminationWeek === weekData.week;
                        return (
                          <Badge
                            key={team}
                            variant={
                              isEliminatedThisWeek ? "destructive" : "secondary"
                            }
                          >
                            {owner?.name}
                          </Badge>
                        );
                      })}
                    </div>
                  </div>
                </div>
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      </CardContent>
    </Card>
  );
};
