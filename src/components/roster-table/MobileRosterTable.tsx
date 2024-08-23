import { Skull } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useLeagueRosters } from "@/queries/useLeagueRosters";
import { useLeagueUsers } from "@/queries/useLeagueUsers";

import { getOwnerByRosterId } from "./getOwnerByRosterId";

type Props = {
  type: "full" | "compact";
};

export const MobileRosterTable = ({ type }: Props) => {
  const {
    data: rosters,
    isLoading: rostersLoading,
    error: rostersError,
  } = useLeagueRosters();
  const {
    data: users,
    isLoading: usersLoading,
    error: usersError,
  } = useLeagueUsers();

  if (rostersLoading || usersLoading) return <div>Loading roster data...</div>;
  if (rostersError || usersError) return <div>Error loading roster data</div>;

  // Combine roster and user data
  const rosterData = rosters?.map((roster) => {
    const leagueUser = users?.find((user) => user.user_id === roster.owner_id);
    const owner = getOwnerByRosterId(roster.roster_id);

    return {
      userId: roster.owner_id,
      teamName: leagueUser?.metadata?.team_name || "Unnamed Team",
      owners: leagueUser?.display_name || "Unknown Owner",
      players: roster.players,
      rosterId: roster.roster_id,
      ownerName: owner?.name,
      isEliminated: owner?.eliminationWeek != null,
      paid: owner?.paid,
    };
  });

  return (
    <ScrollArea className="h-[calc(100vh-200px)]">
      <div className="space-y-4 p-4">
        {rosterData?.map((team) => (
          <Card key={team.rosterId}>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span>{team.teamName}</span>
                {team.isEliminated && <Skull className="h-5 w-5" />}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="mb-2">
                <strong>Owner:</strong> {team.ownerName}
              </div>
              {type === "full" && (
                <>
                  <div className="mb-2 flex gap-2">
                    <strong>ID:</strong> {team.rosterId}
                    {team.paid ? (
                      <Badge className="bg-green-500">Paid</Badge>
                    ) : (
                      <Badge className="bg-red-500">Unpaid</Badge>
                    )}
                  </div>

                  <div>
                    <strong>Players:</strong>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {team.players.map((player) => (
                        <Badge key={player}>{player}</Badge>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </ScrollArea>
  );
};
