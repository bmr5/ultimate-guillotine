import type { CatalogTrade, TradeFilters } from "../types";

function matchesSearch(trade: CatalogTrade, term: string): boolean {
  const needle = term.trim().toLowerCase();
  if (needle === "") return true;
  return trade.assets.some(
    (asset) =>
      asset.kind === "player" && asset.name.toLowerCase().includes(needle),
  );
}

/** Every filter is an AND. An absent filter (null, or an empty search) matches everything. */
export function filterTrades(
  trades: CatalogTrade[],
  filters: TradeFilters,
): CatalogTrade[] {
  return trades.filter((trade) => {
    if (filters.season !== null && trade.season !== filters.season)
      return false;
    if (filters.type !== null && trade.tradeType !== filters.type) return false;
    if (
      filters.position !== null &&
      !trade.assets.some(
        (asset) =>
          asset.kind === "player" && asset.position === filters.position,
      )
    ) {
      return false;
    }
    if (
      filters.memberId !== null &&
      !trade.parties.some((party) => party.memberId === filters.memberId)
    ) {
      return false;
    }
    return matchesSearch(trade, filters.search);
  });
}

export function seasonOptions(trades: CatalogTrade[]): number[] {
  return [...new Set(trades.map((trade) => trade.season))].sort(
    (a, b) => b - a,
  );
}

export function typeOptions(trades: CatalogTrade[]): string[] {
  return [...new Set(trades.map((trade) => trade.tradeType))].sort();
}

export function positionOptions(trades: CatalogTrade[]): string[] {
  const positions = new Set<string>();
  for (const trade of trades) {
    for (const asset of trade.assets) {
      if (asset.kind === "player" && asset.position)
        positions.add(asset.position);
    }
  }
  return [...positions].sort();
}
