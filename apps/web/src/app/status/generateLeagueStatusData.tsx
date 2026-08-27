import { AllGulags } from "@/queries/useLeagueGulagData";

import { Owner } from "../constants";

interface LeagueWeekData {
  week: number;
  gulagTeams: number[];
  genPoolTeams: number[];
  teamsEliminated: number[];
}

export const generateLeagueStatusData = (
  owners: Owner[],
  currentWeek: number,
  gulagData: AllGulags,
): LeagueWeekData[] => {
  const totalWeeks = 17;
  const statusData: LeagueWeekData[] = [];
  console.log("gulag", gulagData);

  for (let week = 1; week <= totalWeeks; week++) {
    if (week <= currentWeek) {
      const weekData: LeagueWeekData = {
        week,
        gulagTeams: [],
        genPoolTeams: [],
        teamsEliminated: [],
      };
      const allEliminatedOwners = Object.keys(gulagData)
        .filter((key) => parseInt(key) <= week && parseInt(key) !== currentWeek)
        .map((key) => gulagData[parseInt(key)]?.lowestScoringCurrentGulag);
      const eliminatedTeam =
        week !== currentWeek
          ? gulagData[week]?.lowestScoringCurrentGulag
          : null;
      const gulagParticipants = gulagData[week - 1]?.incomingGulagParticipants;

      owners.forEach((owner) => {
        if (eliminatedTeam === owner.rosterId) {
          weekData.teamsEliminated.push(owner.rosterId);
        }
        if (gulagParticipants?.includes(owner.rosterId)) {
          weekData.gulagTeams.push(owner.rosterId);
        }
        if (!allEliminatedOwners.includes(owner.rosterId)) {
          weekData.genPoolTeams.push(owner.rosterId);
        }

        if (allEliminatedOwners.includes(owner.rosterId)) {
          if (!weekData.teamsEliminated.includes(owner.rosterId)) {
            weekData.teamsEliminated.push(owner.rosterId);
          }
        }
      });

      // Sort the arrays for consistent display
      weekData.gulagTeams.sort((a, b) => a - b);
      weekData.genPoolTeams.sort((a, b) => a - b);
      weekData.teamsEliminated.sort((a, b) => a - b);

      statusData.push(weekData);
    }
  }

  return statusData;
};
