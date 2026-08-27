import { useQuery } from "@tanstack/react-query";
import axios from "axios";

import { leagueId } from "@/app/constants";

export interface LeagueUser {
  avatar: string;
  user_id: string;
  display_name: string;
  metadata: {
    team_name?: string;
  };
  is_owner: boolean; // is league owner
}

const fetchLeagueUsers = async (): Promise<LeagueUser[]> => {
  const response = await axios.get(
    `https://api.sleeper.app/v1/league/${leagueId}/users`,
  );
  return response.data;
};

export const useLeagueUsers = () => {
  return useQuery<LeagueUser[], Error>({
    queryKey: ["leagueUsers"],
    queryFn: fetchLeagueUsers,
  });
};
