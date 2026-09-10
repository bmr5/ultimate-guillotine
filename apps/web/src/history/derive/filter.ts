import {
  matchesAllTokens,
  normalizeSearchText,
  tokenizeSearchTerm,
} from "@/board/derive/search";

import type { CatalogTrade, TradeFilters } from "../types";

/**
 * The search, folded and tokenised exactly the way the board folds and tokenises its own — the
 * board's helpers, not a second copy of them.
 *
 * `normalizeSearchText` strips accents and the punctuation nobody types, so `Nacua` reaches
 * `Puka Nacuá` and `jamarr` reaches `Ja'Marr Chase`. The term is then a *set of words*, all of
 * which have to land in one player's name in any order, so `nacua puka` finds Puka Nacua on this
 * page for the same reason it finds him on the board — one behaviour to learn, not two.
 *
 * Since the cards carry the league's own announcement of each trade, the term is matched against
 * that text too, and by the same rule: a card that shows a word is a card the search box should
 * find it in. The two are alternatives rather than one pooled haystack — every word has to land
 * in the announcement, or every word in one player's name. Pooling them would make `puka allen`
 * match a Nacua trade announced in a message that happened to mention Allen, which is the very
 * thing the all-tokens rule exists to refuse.
 */
function matchesSearch(trade: CatalogTrade, term: string): boolean {
  const tokens = tokenizeSearchTerm(term);
  if (tokens.length === 0) return true;
  if (
    trade.announcement !== null &&
    matchesAllTokens(normalizeSearchText(trade.announcement), tokens)
  ) {
    return true;
  }
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
