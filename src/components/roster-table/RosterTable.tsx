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

import { getOwnerByRosterId } from "./getOwnerByRosterId";
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

  if (rostersLoading || usersLoading) return <div>Loading roster data...</div>;
  if (rostersError || usersError) return <div>Error loading roster data</div>;

  // Combine roster and user data
  const rosterData: Team[] =
    rosters
      ?.filter((roster) => roster.roster_id !== 18)
      .map((roster) => {
        const leagueUser = users?.find(
          (user) => user.user_id === roster.owner_id,
        );
        const owner = getOwnerByRosterId(roster.roster_id);
        const faab = 1000 - (roster.settings.waiver_budget_used ?? 0);

        const players = useGetPlayersFromRoster(
          roster.players ?? [],
          CURRENT_WEEK,
        );

        return {
          totalPoints: roster.settings.fpts,
          teamName:
            leagueUser?.metadata?.team_name ??
            `${owner?.name ?? "Unknown"}'s Team`,
          ownerName: owner?.name ?? "Unknown Owner",
          isEliminated: owner?.eliminationWeek != null || players.length === 0,
          faab,
          players,
        };
      }) ?? [];

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
