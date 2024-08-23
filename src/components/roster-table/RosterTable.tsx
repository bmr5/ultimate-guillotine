import { Skull } from "lucide-react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useLeagueRosters } from "@/queries/useLeagueRosters";
import { useLeagueUsers } from "@/queries/useLeagueUsers";

import { Badge } from "../ui/badge";
import { getOwnerByRosterId } from "./getOwnerByRosterId";

type Props = {
  type: "full" | "compact";
};

export const RosterTable = ({ type }: Props) => {
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

  // TODO, sort the players by positions. QB, RB, WR, TE, K, DEF

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>
            <Skull />
          </TableHead>
          {type === "full" && <TableHead>ID</TableHead>}
          <TableHead>Team Name</TableHead>
          <TableHead>Owner</TableHead>
          {type === "full" && <TableHead>Players</TableHead>}
          {type === "full" && <TableHead>Paid</TableHead>}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rosterData?.map((team) => (
          <TableRow key={team.rosterId}>
            <TableCell>{team.isEliminated ? <Skull /> : false}</TableCell>
            {type === "full" && <TableCell>{team.rosterId}</TableCell>}

            <TableCell>{team.teamName}</TableCell>
            <TableCell>{team.ownerName}</TableCell>
            {type === "full" && (
              <>
                <TableCell>
                  {team.players.map((player) => (
                    <Badge key={player} className="mr-1">
                      {player}
                    </Badge>
                  ))}
                </TableCell>
                <TableCell>
                  {team.paid ? (
                    <Badge className="bg-green-500">Paid</Badge>
                  ) : (
                    <Badge className="bg-red-500">Unpaid</Badge>
                  )}
                </TableCell>
              </>
            )}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
};
