/** Query keys for the two history pages. Every key starts with `"history"`. */
export const historyKeys = {
  all: ["history"] as const,
  catalog: () => ["history", "trade_catalog"] as const,
  registered: () => ["history", "trades"] as const,
  revisions: () => ["history", "trade_revisions"] as const,
  seasonResults: () => ["history", "season_results"] as const,
  members: () => ["history", "members"] as const,
};
