import { useQueries } from "@tanstack/react-query";
import axios from "axios";

import { CURRENT_WEEK, leagueId } from "@/app/constants";

interface Matchup {
  roster_id: number;
  points: number;
}

export type GulagSummary = {
  // roster IDs for lowest scores of THIS week
  incomingGulagParticipants: Array<number> | null;
  // roster ID for lowest scoring current gulag members (LAST week low scorer)
  lowestScoringCurrentGulag: number | null;
};

export type AllGulags = {
  [key: number]: GulagSummary;
};

const fetchMatchupDataForWeek = async (
  weekNumber: number,
): Promise<Matchup[]> => {
  const response = await axios.get(
    `https://api.sleeper.app/v1/league/${leagueId}/matchups/${weekNumber}`,
  );
  return response.data;
};

export const useLeagueMatchupDataUpToWeek = (weekNumberMax: number) => {
  const queries = [];
  for (let i = 1; i <= weekNumberMax; i++) {
    queries.push({
      queryKey: [`matchupData${i}`],
      queryFn: () => fetchMatchupDataForWeek(i),
    });
  }
  return useQueries({
    queries,
  });
};

export function useLeagueGulagData(): AllGulags {
  const allGulagData: AllGulags = {};
  const allMatchups = useLeagueMatchupDataUpToWeek(CURRENT_WEEK);
  for (let i = 1; i <= CURRENT_WEEK; i++) {
    const { data: matchups } = allMatchups[i - 1];
    const previousWeekLowScorers =
      allGulagData[i - 1]?.incomingGulagParticipants ?? [];
    const incomingGulagParticipants = (matchups ?? [])
      .filter(
        (matchup) =>
          matchup.roster_id != 18 &&
          !previousWeekLowScorers.includes(matchup.roster_id),
      )
      .sort((a, b) => a.points - b.points)
      .slice(0, 2)
      .map(({ roster_id }) => roster_id);
    const lowestScoringCurrentGulag = (matchups ?? [])
      .filter(
        (matchup) =>
          matchup.roster_id != 18 &&
          previousWeekLowScorers.includes(matchup.roster_id),
      )
      .sort((a, b) => a.points - b.points)
      .map(({ roster_id }) => roster_id)[0];
    allGulagData[i] = {
      incomingGulagParticipants,
      lowestScoringCurrentGulag,
    };
  }
  return allGulagData;
}
