import React, { useEffect, useState } from "react";

const LOCAL_JSON_PATH = "/nfl_players.json";

export const PlayerDataManager: React.FC = () => {
  const [playerData, setPlayerData] = useState<any>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchPlayerData = async () => {
      try {
        const response = await fetch(LOCAL_JSON_PATH);
        if (!response.ok) {
          throw new Error("Failed to fetch player data");
        }
        const data = await response.json();
        setPlayerData(data);
        setLastUpdated(
          new Date(
            response.headers.get("last-modified") || "",
          ).toLocaleString(),
        );
        setLoading(false);
      } catch (err) {
        // @ts-ignore
        setError(err.message);
        setLoading(false);
      }
    };

    fetchPlayerData();
  }, []);

  if (loading) {
    return <div>Loading player data...</div>;
  }

  if (error) {
    return <div>Error: {error}</div>;
  }

  return (
    <div>
      <h2>Player Data Loaded</h2>
      <p>Total players: {Object.keys(playerData || {}).length}</p>
      {lastUpdated && <p>Last updated: {lastUpdated}</p>}
      {/* You can add more UI elements here to display or interact with the player data */}
    </div>
  );
};
