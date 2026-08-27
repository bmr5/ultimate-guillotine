import { useQuery } from "@tanstack/react-query";

import { supabase } from "@/supabaseClient";

interface PlayerProjection {
  id: number;
  fantasy_data_id: number;
  rank: number;
  player: string;
  team: string;
  pos: string;
  game_week: number;
  opp: string;
  pass_yds: number;
  pass_td: number;
  pass_int: number;
  rush_yds: number;
  rush_td: number;
  rec: number;
  rec_yds: number;
  rec_td: number;
  def_sck: number;
  def_int: number;
  fum_forced: number;
  fum_recovered: number;
  fpts_ppr: number;
}

const fetchPlayerProjections = async (
  playerNames: string[],
  week: number,
): Promise<PlayerProjection[]> => {
  const { data, error } = await supabase
    .from("player_projections")
    .select("*")
    .in("player", playerNames)
    .eq("game_week", week);

  if (error) {
    throw new Error(`Error fetching projections: ${error.message}`);
  }

  return data || [];
};

export const usePlayerProjections = (playerNames: string[], week: number) => {
  return useQuery<PlayerProjection[], Error>({
    queryKey: ["playerProjections", playerNames, week],
    queryFn: () => fetchPlayerProjections(playerNames, week),
  });
};

// Helper function to get projected PPR points for a specific player
export const getProjectedPPRPoints = (
  projections: PlayerProjection[],
  playerName: string,
): number => {
  const projection = projections.find((p) => p.player === playerName);
  return projection ? projection.fpts_ppr : 0;
};
