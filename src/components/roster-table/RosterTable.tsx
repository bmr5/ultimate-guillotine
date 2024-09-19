import { useContext } from "react";
import { Skull } from "lucide-react";

import { PlayerDataContext } from "@/app/PlayerDataContext";
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
import { getPositionColor } from "./getPositionColor";
import { PlayerBadge } from "./PlayerBadge";

export type Player = {
  id: string;
  name: string;
  position: any;
  team: any;
};

type Props = {
  type: "full" | "compact";
};

export const RosterTable = ({ type }: Props) => {
  const playerData = useContext(PlayerDataContext);

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
  const positionOrder = ["QB", "RB", "WR", "TE", "K", "DEF"];

  const sortPlayersByFantasyOrder = (players: Player[]) => {
    return players.sort((a, b) => {
      const aIndex = positionOrder.indexOf(a.position);
      const bIndex = positionOrder.indexOf(b.position);

      // If both positions are in our order array
      if (aIndex !== -1 && bIndex !== -1) {
        return aIndex - bIndex;
      }

      // If only a's position is in our order array
      if (aIndex !== -1) return -1;

      // If only b's position is in our order array
      if (bIndex !== -1) return 1;

      // If neither position is in our order array, maintain original order
      return 0;
    });
  };

  // Combine roster and user data
  const rosterData = rosters
    ?.map((roster) => {
      if (roster.roster_id === 18) return null;

      const leagueUser = users?.find(
        (user) => user.user_id === roster.owner_id,
      );
      const owner = getOwnerByRosterId(roster.roster_id);
      const faab = 1000 - roster.settings.waiver_budget_used;

      const players: Player[] = (roster.players ?? []).map((pID) => {
        const player = playerData[pID];
        return {
          id: pID,
          name: player ? `${player.first_name} ${player.last_name}` : pID,
          position: player?.position,
          team: player?.team,
        };
      });

      const sortedPlayers = sortPlayersByFantasyOrder(players);

      return {
        userId: roster.owner_id,
        teamName: leagueUser?.metadata?.team_name || `${owner?.name}'s Team`,
        owners: leagueUser?.display_name || "Unknown Owner",
        players: sortedPlayers,
        rosterId: roster.roster_id,
        ownerName: owner?.name,
        isEliminated:
          owner?.eliminationWeek != null ||
          (roster?.players ?? []).length === 0,
        paid: owner?.paid,
        faab,
      };
    })
    .filter(Boolean);

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
          {type === "full" && <TableHead>$</TableHead>}
          {type === "full" && (
            <TableHead className="flex items-center gap-2">
              <p>Players</p>
              <div className="mt-1 flex flex-wrap">
                {positionOrder.map((position) => (
                  <Badge
                    key={position}
                    className={`mb-1 mr-1 ${getPositionColor(position)}`}
                  >
                    {position}
                  </Badge>
                ))}
              </div>
            </TableHead>
          )}
          {/* {type === "full" && <TableHead>Paid</TableHead>} */}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rosterData?.map((team) => {
          if (team != null) {
            return (
              <TableRow key={team.rosterId}>
                <TableCell>{team.isEliminated ? <Skull /> : false}</TableCell>
                {type === "full" && <TableCell>{team.rosterId}</TableCell>}
                <TableCell>{team.teamName}</TableCell>
                <TableCell>{team.ownerName}</TableCell>
                <TableCell>{team.faab}</TableCell>
                {type === "full" && (
                  <>
                    <TableCell>
                      {team.players.map((player) => (
                        <PlayerBadge key={player.id} player={player} />
                      ))}
                    </TableCell>
                    {/* <TableCell>
                      {team.paid ? (
                        <Badge className="bg-green-500">Paid</Badge>
                      ) : (
                        <Badge className="bg-red-500">Unpaid</Badge>
                      )}
                    </TableCell> */}
                  </>
                )}
              </TableRow>
            );
          }
        })}
      </TableBody>
    </Table>
  );
};
