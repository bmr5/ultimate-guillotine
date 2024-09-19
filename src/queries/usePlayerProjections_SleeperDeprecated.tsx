import { useQuery } from "@tanstack/react-query";
import axios from "axios";

interface PlayerStatEntry {
  date: string;
  stats: {
    gms_active?: number;
    pos_rank_half_ppr?: number;
    pos_rank_ppr?: number;
    pos_rank_std?: number;
    bonus_fd_wr?: number;
    bonus_rec_wr?: number;
    gp?: number;
    gs?: number;
    off_snp?: number;
    pts_half_ppr?: number;
    pts_ppr?: number;
    pts_std?: number;
    rec?: number;
    rec_air_yd?: number;
    rec_fd?: number;
    rec_lng?: number;
    rec_tgt?: number;
    rec_yar?: number;
    rec_yd?: number;
    rec_ypr?: number;
    rec_ypt?: number;
    rush_rec_yd?: number;
    tm_def_snp?: number;
    tm_off_snp?: number;
    tm_st_snp?: number;
    anytime_tds?: number;
    rec_td?: number;
    rush_att?: number;
    rush_lng?: number;
    rush_td?: number;
    rush_yd?: number;
    rush_ypa?: number;
    fum?: number;
    rec_drop?: number;
    [key: string]: number | undefined;
  };
  category: string;
  last_modified: number | null;
  week: number;
  season: string;
  season_type: string;
  sport: string;
  player_id: string;
  game_id: string;
  updated_at: number | null;
  team: string;
  company: string;
  opponent: string;
}

interface PlayerStatsResponse {
  [week: string]: PlayerStatEntry | null;
}

const fetchPlayerProjections = async (
  playerId: string,
  season: string = "2024",
  seasonType: string = "regular",
): Promise<PlayerStatsResponse> => {
  const response = await axios.get<PlayerStatsResponse>(
    `https://api.sleeper.com/stats/nfl/player/${playerId}?season_type=${seasonType}&season=${season}&grouping=week`,
  );
  return response.data;
};

export const usePlayerProjections = (
  playerId: string,
  season: string = "2024",
  seasonType: string = "regular",
) => {
  return useQuery<PlayerStatsResponse, Error>({
    queryKey: ["playerProjections", playerId, season, seasonType],
    queryFn: () => fetchPlayerProjections(playerId, season, seasonType),
  });
};

export const getProjectedPoints = (
  projections: PlayerStatsResponse,
  week: number,
): number => {
  const projection = projections[week.toString()];
  return projection ? projection.stats.pts_ppr || 0 : 0;
};
