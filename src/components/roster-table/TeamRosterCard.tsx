import { Skull } from "lucide-react";

import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { Separator } from "../ui/separator";
import { Player } from "./RosterTable";

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
};

const positionOrder = ["QB", "RB", "WR", "TE", "K", "DEF"];

export const TeamRosterCard = ({ team }: TeamRosterCardProps) => {
  const { teamName, ownerName, isEliminated, faab, players, totalPoints } =
    team;

  // Calculate player counts for each position
  const positionCounts = players.reduce(
    (counts, player) => {
      counts[player.position] = (counts[player.position] || 0) + 1;
      return counts;
    },
    {} as Record<string, number>,
  );

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
              <div className="flex space-x-2 font-semibold">
                <span>{position}</span>
                <span className="text-muted-foreground">
                  ({positionCounts[position] || 0})
                </span>
              </div>
              <Separator />
              {players
                .filter((player) => player.position === position)
                .map((player) => (
                  <div key={player.id} className="text-sm">
                    {player.name} {player.team && `(${player.team})`}
                  </div>
                ))}
            </div>
          ))}
        </div>
      </CardContent>
      <CardFooter className="bg-primary/10 px-4 py-2 text-sm font-medium">
        Total Points: {totalPoints.toFixed(2)}
      </CardFooter>
    </Card>
  );
};
