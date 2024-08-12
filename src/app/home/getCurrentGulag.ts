import { Owner, simulatedOwners } from "@/app/constants";

export const getCurrentGulag = (currentWeek: number): Owner[] => {
  return simulatedOwners.filter((owner) =>
    owner.gulagWeeks.includes(currentWeek),
  );
  //   return owners.filter((owner) => owner.gulagWeeks.includes(currentWeek));
};
