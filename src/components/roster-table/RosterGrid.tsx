import { useState } from "react";

import { CURRENT_WEEK } from "@/app/constants";
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
import { getRosterData } from "./getRosterData";
import { Team, TeamRosterCard } from "./TeamRosterCard";
import { useGetPlayersFromRoster } from "./useGetPlayersFromRoster";

export const RosterGrid = () => {
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

  const [sortBy, setSortBy] = useState<"faab" | "teamName" | "totalPoints">(
    "faab",
  );
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [showOnlyActive, setShowOnlyActive] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");

  const rosterData: Team[] = getRosterData({
    rosters: rosters ?? [],
    users: users ?? [],
    allRostersPlayerData,
  });

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
      } else if (sortBy === "totalPoints") {
        return sortOrder === "asc"
          ? a.totalPoints - b.totalPoints
          : b.totalPoints - a.totalPoints;
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
          onValueChange={(value) =>
            setSortBy(value as "faab" | "teamName" | "totalPoints")
          }
        >
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="Sort by" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="faab">Sort by FAAB</SelectItem>
            <SelectItem value="teamName">Sort by Team Name</SelectItem>
            <SelectItem value="totalPoints">Sort by Total Points</SelectItem>
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
              <TeamRosterCard key={index} team={team} week={CURRENT_WEEK} />
            ) : null;
          })}
        </div>
      </ScrollArea>
    </div>
  );
};
