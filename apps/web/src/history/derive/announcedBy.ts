import type { CatalogTrade } from "../types";

/** `announced by <owner>` for a registered trade whose sender was placed; empty otherwise. */
export function announcedByLine(trade: CatalogTrade): string {
  return trade.announcedBy === null ? "" : `announced by ${trade.announcedBy}`;
}
