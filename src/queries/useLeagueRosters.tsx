import { useQuery } from "@tanstack/react-query";
import axios from "axios";

import { leagueId } from "@/app/constants";

interface Roster {
  roster_id: number;
  owner_id: string;
  players: string[];
  // Add more fields as needed based on the Sleeper API response
}

const fetchRosters = async (): Promise<Roster[]> => {
  const response = await axios.get(
    `https://api.sleeper.app/v1/league/${leagueId}/rosters`,
  );
  return response.data;
};

export const useLeagueRosters = () => {
  return useQuery<Roster[], Error>({
    queryKey: ["rosters"],
    queryFn: () => fetchRosters(),
  });
};
