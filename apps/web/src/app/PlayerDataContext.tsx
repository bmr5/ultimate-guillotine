import React, { useEffect, useState } from "react";

export const PlayerDataContext = React.createContext<Record<string, any>>({});

type PlayerDataProviderProps = {
  children: React.ReactNode;
};

export const PlayerDataProvider = ({ children }: PlayerDataProviderProps) => {
  const [playerData, setPlayerData] = useState<Record<string, any>>({});

  useEffect(() => {
    fetch("/nfl_players.json")
      .then((response) => response.json())
      .then((data) => {
        setPlayerData(data);
      });
  }, []);

  return (
    <PlayerDataContext.Provider value={playerData}>
      {children}
    </PlayerDataContext.Provider>
  );
};
