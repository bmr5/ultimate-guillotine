import {
  matchesAllTokens,
  normalizeSearchText,
  tokenizeSearchTerm,
} from "@/board/derive/search";

import type { CatalogTrade, TradeFilters } from "../types";

/**
 * The player-name search, folded and tokenised exactly the way the board folds and tokenises its
 * own — the board's helpers, not a second copy of them.
 *
 * `normalizeSearchText` strips accents and the punctuation nobody types, so `Nacua` reaches
 * `Puka Nacuá` and `jamarr` reaches `Ja'Marr Chase`. The term is then a *set of words*, all of
 * which have to land in one player's name in any order, so `nacua puka` finds Puka Nacua on this
 * page for the same reason it finds him on the board — one behaviour to learn, not two.
 */
function matchesSearch(trade: CatalogTrade, term: string): boolean {
  const tokens = tokenizeSearchTerm(term);
  if (tokens.length === 0) return true;
  return trade.assets.some(
    (asset) =>
      asset.kind === "player" &&
      matchesAllTokens(normalizeSearchText(asset.name), tokens),
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
