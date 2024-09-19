import { useMemo } from "react";
import { Skull } from "lucide-react";

import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  getProjectedPPRPoints,
  usePlayerProjections,
} from "@/queries/usePlayerProjections";

import { Separator } from "../ui/separator";
import { Player } from "./useGetPlayersFromRoster";

export type Team = {
  totalPoints: number;
  teamName: string;
  ownerName: string;
  isEliminated: boolean;
  faab: number;
  players: Player[];
};

type TeamRosterCardProps = {
  team: Team;
  week: number;
};

const positionOrder = ["QB", "RB", "WR", "TE", "K", "DEF"];

export const TeamRosterCard = ({ team, week }: TeamRosterCardProps) => {
  const { teamName, ownerName, isEliminated, faab, players, totalPoints } =
    team;

  const playerNames = players.map((player) => player.name);
  const { data: projections, isLoading: projectionsLoading } =
    usePlayerProjections(playerNames, week);

  const { positionCounts, positionProjections, totalProjectedPoints } =
    useMemo(() => {
      const counts = {} as Record<string, number>;
      const projectedPoints = {} as Record<string, number>;
      let total = 0;

      players.forEach((player) => {
        counts[player.position] = (counts[player.position] || 0) + 1;
        if (projections) {
          const points = getProjectedPPRPoints(projections, player.name);
          projectedPoints[player.position] =
            (projectedPoints[player.position] || 0) + points;
          total += points;
        }
      });

      return {
        positionCounts: counts,
        positionProjections: projectedPoints,
        totalProjectedPoints: total,
      };
    }, [players, projections]);

  return (
    <Card
      className={cn(
        "flex flex-col overflow-hidden",
        isEliminated && "bg-gray-200 opacity-75 dark:bg-gray-800",
      )}
    >
      <CardHeader
        className={cn(
          "py-2",
          isEliminated ? "bg-red-200 dark:bg-red-900" : "bg-secondary",
        )}
      >
        <CardTitle className="flex items-center justify-between text-sm">
          <div className="flex items-center space-x-2">
            <span className={cn(isEliminated && "line-through")}>
              {teamName}
            </span>
            {isEliminated && <Skull className="h-4 w-4 text-red-500" />}
            <span className="text-muted-foreground">({ownerName})</span>
          </div>
          <span className="text-muted-foreground">FAAB: ${faab}</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-grow p-4">
        <div className="grid grid-cols-2 gap-4">
          {positionOrder.map((position) => (
            <div key={position} className="space-y-1">
              <div className="flex gap-1 font-semibold">
                <span>{position}</span>
                <span className="text-muted-foreground">
                  ({positionCounts[position] || 0}){" -"}
                  {!projectionsLoading && projections && (
                    <span className="ml-2">
                      {positionProjections[position]?.toFixed(1) || "0.0"}
                    </span>
                  )}
                </span>
              </div>
              <Separator />
              {players
                .filter((player) => player.position === position)
                .map((player) => (
                  <div key={player.id} className="flex justify-between text-sm">
                    <span>
                      {player.name} {player.team && `(${player.team})`}
                    </span>
                    {projectionsLoading ? (
                      <span className="text-muted-foreground">Loading...</span>
                    ) : (
                      <span className="text-muted-foreground">
                        {projections
                          ? getProjectedPPRPoints(
                              projections,
                              player.name,
                            ).toFixed(1)
                          : "N/A"}
                      </span>
                    )}
                  </div>
                ))}
            </div>
          ))}
        </div>
      </CardContent>
      <CardFooter className="bg-primary/10 px-4 py-2 text-sm font-medium">
        <div className="flex w-full justify-between">
          <span>Total Points: {totalPoints.toFixed(2)}</span>
          <span>
            Projected:{" "}
            {projectionsLoading
              ? "Loading..."
              : totalProjectedPoints.toFixed(2)}
          </span>
        </div>
      </CardFooter>
    </Card>
  );
};
