import { Roster } from "@/queries/useLeagueRosters";
import { LeagueUser } from "@/queries/useLeagueUsers";

import { getOwnerByRosterId } from "./getOwnerByRosterId";
import { Team } from "./TeamRosterCard";
import { Player } from "./useGetPlayersFromRoster";

type Params = {
  rosters: Roster[];
  users: LeagueUser[];
  allRostersPlayerData: Player[];
};

export const getRosterData = ({
  rosters,
  users,
  allRostersPlayerData,
}: Params) => {
  const rosterData: Team[] =
    rosters
      ?.filter((roster) => roster.roster_id !== 18)
      .map((roster) => {
        const leagueUser = users?.find(
          (user) => user.user_id === roster.owner_id,
        );
        const owner = getOwnerByRosterId(roster.roster_id);
        const faab = 1000 - (roster.settings.waiver_budget_used ?? 0);

        const players = allRostersPlayerData.filter(
          (player) => roster.players?.includes(player.id),
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

  return rosterData;
};
