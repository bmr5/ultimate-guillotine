import React, { useEffect, useState } from "react";

export type PlayerDataRecord = {
  first_name?: string | null;
  last_name?: string | null;
  position?: string | null;
  team?: string | null;
};

export type PlayerData = Record<string, PlayerDataRecord>;

export const PlayerDataContext = React.createContext<PlayerData>({});

type PlayerDataProviderProps = {
  children: React.ReactNode;
};

export const PlayerDataProvider = ({ children }: PlayerDataProviderProps) => {
  const [playerData, setPlayerData] = useState<PlayerData>({});

  useEffect(() => {
    fetch("/nfl_players.json")
      .then((response) => response.json())
      .then((data: PlayerData) => {
        setPlayerData(data);
      });
  }, []);

  return (
    <PlayerDataContext.Provider value={playerData}>
      {children}
    </PlayerDataContext.Provider>
  );
};
