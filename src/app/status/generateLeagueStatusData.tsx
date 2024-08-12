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
): LeagueWeekData[] => {
  const totalWeeks = 17;
  const statusData: LeagueWeekData[] = [];

  for (let week = 1; week <= totalWeeks; week++) {
    if (week <= currentWeek) {
      const weekData: LeagueWeekData = {
        week,
        gulagTeams: [],
        genPoolTeams: [],
        teamsEliminated: [],
      };

      owners.forEach((owner) => {
        if (owner.eliminationWeek === week) {
          weekData.teamsEliminated.push(owner.rosterId);
        }
        if (owner.gulagWeeks.includes(week)) {
          weekData.gulagTeams.push(owner.rosterId);
        }
        if (owner.eliminationWeek === null || owner.eliminationWeek > week) {
          weekData.genPoolTeams.push(owner.rosterId);
        }

        if (owner.eliminationWeek && owner.eliminationWeek <= week) {
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
