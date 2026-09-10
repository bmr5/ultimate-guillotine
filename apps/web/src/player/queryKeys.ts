/** The player card's keys. Every key starts with `"player"`. */
export const playerKeys = {
  all: ["player"] as const,
  transactions: (seasonId: number, sleeperPlayerId: string) =>
    ["player", "transactions", seasonId, sleeperPlayerId] as const,
  seasonScores: (seasonId: number) =>
    ["player", "season_scores", seasonId] as const,
  directory: (sleeperPlayerIds: readonly string[]) =>
    ["player", "directory", [...new Set(sleeperPlayerIds)].sort()] as const,
};
