/** Query keys for the two history pages. Every key starts with `"history"`. */
export const historyKeys = {
  catalog: () => ["history", "trade_catalog"] as const,
  registered: () => ["history", "trades"] as const,
  revisions: () => ["history", "trade_revisions"] as const,
  seasonResults: () => ["history", "season_results"] as const,
  members: () => ["history", "members"] as const,
  /**
   * Keyed on the ids themselves, sorted and deduped here so the key is canonical: two renders
   * that need the same players hit the same cache entry whatever order the trades listed them
   * in, and a newly referenced player is a cache miss rather than a directory that cannot name
   * him. The list is short — the assets on one page of trades, not the whole directory.
   */
  players: (sleeperPlayerIds: readonly string[]) =>
    ["history", "players", [...new Set(sleeperPlayerIds)].sort()] as const,
};
