import { Owner, owners } from "@/app/constants";

export const getCurrentGulag = (currentWeek: number): Owner[] => {
  return owners.filter((owner) => owner.gulagWeeks.includes(currentWeek));
};
