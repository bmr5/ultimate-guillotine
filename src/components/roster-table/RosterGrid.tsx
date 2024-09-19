import { useContext, useState } from "react";

import { PlayerDataContext } from "@/app/PlayerDataContext";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useLeagueRosters } from "@/queries/useLeagueRosters";
import { useLeagueUsers } from "@/queries/useLeagueUsers";

import { getOwnerByRosterId } from "./getOwnerByRosterId";
import { Player } from "./RosterTable";
import { TeamRosterCard } from "./TeamRosterCard";

interface Team {
  teamName: string;
  ownerName: string;
  isEliminated: boolean;
  faab: number;
  players: Player[];
}

type Props = {
  type: "full" | "compact";
};

export const RosterGrid = ({ type }: Props) => {
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

  const [sortBy, setSortBy] = useState<"faab" | "teamName">("faab");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [showOnlyActive, setShowOnlyActive] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");

  const positionOrder = ["QB", "RB", "WR", "TE", "K", "DEF"];

  const sortPlayersByFantasyOrder = (players: Player[]): Player[] => {
    return [...players].sort((a, b) => {
      const aIndex = positionOrder.indexOf(a.position ?? "");
      const bIndex = positionOrder.indexOf(b.position ?? "");
      if (aIndex !== -1 && bIndex !== -1) return aIndex - bIndex;
      if (aIndex !== -1) return -1;
      if (bIndex !== -1) return 1;
      return 0;
    });
  };

  const rosterData: Team[] =
    rosters
      ?.filter((roster) => roster.roster_id !== 18)
      .map((roster) => {
        const leagueUser = users?.find(
          (user) => user.user_id === roster.owner_id,
        );
        const owner = getOwnerByRosterId(roster.roster_id);
        const faab = 1000 - (roster.settings.waiver_budget_used ?? 0);

        const players: Player[] = (roster.players ?? []).map((pID) => {
          const player = playerData[pID];
          return {
            id: pID,
            name: player ? `${player.first_name} ${player.last_name}` : pID,
            position: player?.position ?? "Unknown",
            team: player?.team ?? "Unknown",
          };
        });

        const sortedPlayers = sortPlayersByFantasyOrder(players);

        return {
          teamName:
            leagueUser?.metadata?.team_name ??
            `${owner?.name ?? "Unknown"}'s Team`,
          ownerName: owner?.name ?? "Unknown Owner",
          isEliminated: owner?.eliminationWeek != null || players.length === 0,
          faab,
          players: sortedPlayers,
        };
      }) ?? [];

  const filteredAndSortedRosterData = rosterData
    .filter((team) => {
      if (showOnlyActive && team.isEliminated) return false;
      if (searchTerm) {
        const searchLower = searchTerm.toLowerCase();
        return (
          team.teamName.toLowerCase().includes(searchLower) ||
          team.ownerName.toLowerCase().includes(searchLower) ||
          team.players.some((player) =>
            player.name.toLowerCase().includes(searchLower),
          )
        );
      }
      return true;
    })
    .sort((a, b) => {
      if (sortBy === "faab") {
        return sortOrder === "asc" ? a.faab - b.faab : b.faab - a.faab;
      } else {
        return sortOrder === "asc"
          ? a.teamName.localeCompare(b.teamName)
          : b.teamName.localeCompare(a.teamName);
      }
    });

  if (rostersLoading || usersLoading) return <div>Loading roster data...</div>;
  if (rostersError || usersError) return <div>Error loading roster data</div>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-4">
        <Input
          placeholder="Search teams or players..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="max-w-xs"
        />
        <Select
          value={sortBy}
          onValueChange={(value) => setSortBy(value as "faab" | "teamName")}
        >
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="Sort by" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="faab">Sort by FAAB</SelectItem>
            <SelectItem value="teamName">Sort by Team Name</SelectItem>
          </SelectContent>
        </Select>
        <Select
          value={sortOrder}
          onValueChange={(value) => setSortOrder(value as "asc" | "desc")}
        >
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="Sort order" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="asc">Ascending</SelectItem>
            <SelectItem value="desc">Descending</SelectItem>
          </SelectContent>
        </Select>
        <div className="flex items-center space-x-2">
          <Checkbox
            id="showOnlyActive"
            checked={showOnlyActive}
            onCheckedChange={(checked) => setShowOnlyActive(checked as boolean)}
          />
          <label htmlFor="showOnlyActive">Show only active teams</label>
        </div>
      </div>

      <ScrollArea className="">
        <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredAndSortedRosterData?.map((team, index) => {
            return team != null ? (
              <TeamRosterCard
                key={index}
                teamName={team.teamName}
                ownerName={team.ownerName}
                isEliminated={team.isEliminated}
                faab={team.faab}
                players={team.players}
                type={type}
              />
            ) : null;
          })}
        </div>
      </ScrollArea>
    </div>
  );
};
