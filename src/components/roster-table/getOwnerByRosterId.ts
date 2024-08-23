import { Owner, owners } from "@/app/constants";

export const getOwnerByRosterId = (rosterId: number): Owner | undefined => {
  return owners.find((owner) => owner.rosterId === rosterId);
  // return simulatedOwners.find((owner) => owner.rosterId === rosterId);
};
