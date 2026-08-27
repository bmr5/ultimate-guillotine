// src/hooks/useGetPlayersFromRoster.ts
import { useContext, useMemo } from "react";

import { PlayerDataContext } from "@/app/PlayerDataContext";
import { usePlayerProjections } from "@/queries/usePlayerProjections";

export type Player = {
  id: string;
  name: string;
  position: string;
  team: string;
  projectedPoints: number | null;
};

const positionOrder = ["QB", "RB", "WR", "TE", "K", "DEF"];

export const useGetPlayersFromRoster = (
  rosterPlayers: string[],
  week: number,
) => {
  const playerData = useContext(PlayerDataContext);
  const playerNames = rosterPlayers.map((pID) => {
    const player = playerData[pID];
    return player ? `${player.first_name} ${player.last_name}` : pID;
  });

  const { data: projections } = usePlayerProjections(playerNames, week);

  const players: Player[] = useMemo(() => {
    return rosterPlayers.map((pID) => {
      const player = playerData[pID];
      const name = player ? `${player.first_name} ${player.last_name}` : pID;
      const projection = projections?.find((p) => p.player === name);

      return {
        id: pID,
        name,
        position: player?.position ?? "Unknown",
        team: player?.team ?? "Unknown",
        projectedPoints: projection?.fpts_ppr ?? null,
      };
    });
  }, [rosterPlayers, playerData, projections]);

  const sortPlayersByFantasyOrder = (players: Player[]): Player[] => {
    return [...players].sort((a, b) => {
      const aIndex = positionOrder.indexOf(a.position ?? "");
      const bIndex = positionOrder.indexOf(b.position ?? "");
      if (aIndex !== -1 && bIndex !== -1) return aIndex - bIndex;
      if (aIndex !== -1) return -1;
      if (bIndex !== -1) return 1;
      return 0;
    });
  };

  const sortedPlayers = useMemo(
    () => sortPlayersByFantasyOrder(players),
    [players],
  );

  return sortedPlayers;
};
