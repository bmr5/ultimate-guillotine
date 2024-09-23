import { Skull } from "lucide-react";

import { CURRENT_WEEK } from "@/app/constants";
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

import { getRosterData } from "./getRosterData";
import { Team } from "./TeamRosterCard";
import { useGetPlayersFromRoster } from "./useGetPlayersFromRoster";

export const RosterTable = () => {
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

  const allPlayersOnRosters =
    rosters?.reduce<string[]>(
      (acc, roster) => [...acc, ...(roster.players ?? [])],
      [],
    ) ?? [];

  const allRostersPlayerData = useGetPlayersFromRoster(
    allPlayersOnRosters,
    CURRENT_WEEK,
  );
  const rosterData: Team[] = getRosterData({
    rosters: rosters ?? [],
    users: users ?? [],
    allRostersPlayerData,
  });

  if (rostersLoading || usersLoading) return <div>Loading roster data...</div>;
  if (rostersError || usersError) return <div>Error loading roster data</div>;

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>
            <Skull />
          </TableHead>
          <TableHead>Team Name</TableHead>
          <TableHead>Owner</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rosterData?.map((team) => {
          if (team != null) {
            return (
              <TableRow key={team.ownerName}>
                <TableCell>{team.isEliminated ? <Skull /> : false}</TableCell>
                <TableCell>{team.teamName}</TableCell>
                <TableCell>{team.ownerName}</TableCell>
                <TableCell>${team.faab}</TableCell>
              </TableRow>
            );
          }
        })}
      </TableBody>
    </Table>
  );
};
