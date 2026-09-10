import type { CatalogTrade } from "../types";

export interface TradeStats {
  tradeCount: number;
  seasonCount: number;
}

/** The strip under the filters. Computed over the filtered set, so it answers the view. */
export function tradeStats(trades: CatalogTrade[]): TradeStats {
  const seasons = new Set<number>();
  for (const trade of trades) {
    seasons.add(trade.season);
  }
  return { tradeCount: trades.length, seasonCount: seasons.size };
}
