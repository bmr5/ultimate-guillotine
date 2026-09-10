export type Confidence = "high" | "medium" | "low";

export type TradeAsset =
  | {
      kind: "player";
      playerId: string | null;
      name: string;
      position: string | null;
      fromParty: number | null;
      toParty: number | null;
    }
  | {
      kind: "faab";
      amount: number;
      fromParty: number | null;
      toParty: number | null;
    }
  | { kind: "condition"; label: string };

export interface TradeParty {
  memberId: number;
  label: string;
  /**
   * Whether `label` is this party's own name or the word that stands in for one.
   *
   * `false` where the directory carries nobody for the id: the party keeps its place, but its
   * label is `FORMER_MANAGER` rather than anybody's name. The flag is needed because the label
   * alone cannot be read back — a caller that folds the parties it cannot name into one counted
   * segment would otherwise have to compare against that string to tell them apart, and a
   * manager nicknamed the same thing would fold with them.
   */
  resolved: boolean;
}

/** One row on `/trades`, whether it came from the catalog or from a registered trade. */
export interface CatalogTrade {
  key: string;
  season: number;
  week: number | null;
  occurredOn: string | null;
  tradeType: string;
  structure: string;
  parties: TradeParty[];
  /** How many people were in the deal, including any the loader could not resolve. */
  partyCount: number;
  /**
   * Every asset the deal moved, for the search box and nothing else.
   *
   * Ben's ruling of 2026-09-09 took the asset list off the card: "we just want to log the
   * Participants, the date and time, a category, and the exact text". The assets stay in the
   * derived row because `filterTrades` matches player names against them — a trade is still
   * findable by who was in it — and because `resolvePlayerNames` is what turns a registered
   * asset's bare `player_id` into a name to match. Nothing renders them.
   */
  assets: TradeAsset[];
  confidence: Confidence;
  /**
   * What the league said when the trade was made, or `null` when there is nothing to quote.
   *
   * The one piece of league chat these pages carry, by Ben's ruling of 2026-09-10: the tiles
   * were unreadable as a taxonomy alone. A catalog row's comes from the classification file's
   * `source_texts`, joined a message per paragraph; a registered row's is the excerpt the
   * Registrar quoted when it recorded the deal. `null` renders as nothing — never as an empty
   * quote block, which would say the league said nothing rather than that nothing was kept.
   */
  announcement: string | null;
  /**
   * When the Registrar recorded a registered trade, ISO-8601, or `null` for a catalog row.
   *
   * The catalog is a reading of a spreadsheet and knows only the season and the week (or, for a
   * handful of rows, the day), so it has no instant to carry and its cards are still dated
   * `Season 2024 · Week 3`. A registered trade has one, and Ben's ruling of 2026-09-09 is that
   * the card shows it: "we just want to log the Participants, the date and time, a category,
   * and the exact text". Kept as the raw string rather than an epoch so the formatter, not the
   * data layer, decides the viewer's timezone and locale.
   */
  registeredAt: string | null;
  /** The trade code for a registered row, the literal `catalog` for a catalog row. */
  sourceLabel: string;
  registered: boolean;
  rescinded: boolean;
  unresolvedParties: number;
}

export interface TradeFilters {
  season: number | null;
  type: string | null;
  position: string | null;
  memberId: number | null;
  search: string;
}

export const EMPTY_FILTERS: TradeFilters = {
  season: null,
  type: null,
  position: null,
  memberId: null,
  search: "",
};

/** Parse a URL query value into a number, or null when it is absent or not a number. */
export function parseNumberParam(value: string | null): number | null {
  if (value === null || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * One week's row of a season's elimination grid.
 *
 * Two counts and no third: the loader (`history/records.py`, `_entry`) writes `week`, `order`,
 * `member_id`, `gulag_out`, `pool_out` and `note`, and nothing else. There is no surviving-team
 * figure to carry — both workbook grids hold that column as an uncached formula, so the reader
 * never sees a number for it — and a season without a general pool (2023) has no `pool_out`
 * cell at all. Every figure is therefore nullable, and `null` means "the sheet never said",
 * which is not `0`.
 */
export interface SeasonElimination {
  week: number;
  order: number;
  memberId: number | null;
  gulagOut: number | null;
  poolOut: number | null;
}

/**
 * One season's finish.
 *
 * Every placing carries both the label and the id it was resolved from, because a `null`
 * label answers two different questions with the same word: the row named somebody the
 * members directory cannot name (a manager who has left), or the row named nobody at all
 * (a champion never recorded). `seasonPlacingLabel` is the one place that tells them apart,
 * and it needs the id to do it.
 */
export interface SeasonResult {
  season: number;
  championLabel: string | null;
  championMemberId: number | null;
  coChampionLabel: string | null;
  coChampionMemberId: number | null;
  runnerUpLabel: string | null;
  runnerUpMemberId: number | null;
  thirdLabel: string | null;
  thirdMemberId: number | null;
  teamCount: number | null;
  eliminations: SeasonElimination[];
  notes: string | null;
  loadedAt: string;
}
