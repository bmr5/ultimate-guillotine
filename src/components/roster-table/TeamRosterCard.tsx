import { Skull } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { Player } from "./RosterTable";

type TeamRosterCardProps = {
  teamName: string;
  ownerName: string;
  isEliminated: boolean;
  faab: number;
  players: Player[];
  type: "full" | "compact";
};

const positionOrder = ["QB", "RB", "WR", "TE", "K", "DEF"];

export const TeamRosterCard = ({
  teamName,
  ownerName,
  isEliminated,
  faab,
  players,
}: TeamRosterCardProps) => {
  return (
    <Card
      className={cn(
        "overflow-hidden",
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
      <CardContent className="p-4">
        <div className="grid grid-cols-2 gap-2">
          {positionOrder.map((position) => (
            <div key={position} className="space-y-1">
              <div className="font-semibold">{position}</div>
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
    </Card>
  );
};
