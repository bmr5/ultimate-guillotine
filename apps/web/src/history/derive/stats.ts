import type { CatalogTrade } from "../types";

export interface TradeStats {
  tradeCount: number;
  seasonCount: number;
  faabMoved: number;
  topPosition: string | null;
}

/** The strip under the filters. Computed over the filtered set, so it answers the view. */
export function tradeStats(trades: CatalogTrade[]): TradeStats {
  const seasons = new Set<number>();
  const positions = new Map<string, number>();
  let faabMoved = 0;

  for (const trade of trades) {
    seasons.add(trade.season);
    // A rescinded trade's FAAB never moved: the deal was undone, so counting it would have the
    // strip claim budget changed hands when it did not. The trade itself is still counted and
    // still shown — it happened, it just did not stick.
    if (!trade.rescinded) faabMoved += trade.faabTotal ?? 0;
    for (const asset of trade.assets) {
      if (asset.kind === "player" && asset.position) {
        positions.set(asset.position, (positions.get(asset.position) ?? 0) + 1);
      }
    }
  }

  let topPosition: string | null = null;
  let topCount = 0;
  // Ties break alphabetically, so the strip does not flicker between equal positions.
  for (const position of [...positions.keys()].sort()) {
    const count = positions.get(position) ?? 0;
    if (count > topCount) {
      topPosition = position;
      topCount = count;
    }
  }

  return {
    tradeCount: trades.length,
    seasonCount: seasons.size,
    faabMoved,
    topPosition,
  };
}
