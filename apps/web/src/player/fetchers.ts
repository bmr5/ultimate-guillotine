import type { BoardClient } from "@/board/fetchers";
import type { TableRow } from "@/board/types";

export type TransactionRow = Pick<
  TableRow<"transactions">,
  "id" | "kind" | "week" | "occurred_at" | "team_ids" | "faab_moves" | "waiver_bid"
>;
export type TransactionMoveRow = Pick<
  TableRow<"transaction_moves">,
  "transaction_id" | "sleeper_player_id" | "team_id" | "action"
>;
export type SeasonScoreRow = Pick<
  TableRow<"team_week_scores">,
  "week" | "team_id" | "players_points"
>;

interface SupabaseResult<T> {
  data: T[] | null;
  error: { message: string } | null;
}

async function unwrap<T>(
  query: PromiseLike<SupabaseResult<T>>,
  label: string,
): Promise<T[]> {
  const { data, error } = await query;
  if (error !== null) {
    throw new Error(`${label}: ${error.message}`);
  }
  return data ?? [];
}

export interface PlayerTransactions {
  transactions: TransactionRow[];
  /** Every move of every transaction the player was in — his own and the other players'. */
  moves: TransactionMoveRow[];
}

/**
 * Everything that has happened to one player this season, in two hops: the transactions his
 * own moves name, then every row of those transactions so a trade entry can name the other
 * players and the FAAB that moved with him. `raw` is never selected.
 */
export async function fetchPlayerTransactions(
  client: BoardClient,
  seasonId: number,
  sleeperPlayerId: string,
): Promise<PlayerTransactions> {
  const own = await unwrap<Pick<TransactionMoveRow, "transaction_id">>(
    client
      .from("transaction_moves")
      .select("transaction_id")
      .eq("season_id", seasonId)
      .eq("sleeper_player_id", sleeperPlayerId),
    "transaction_moves",
  );
  const ids = [...new Set(own.map((row) => row.transaction_id))];
  if (ids.length === 0) {
    return { transactions: [], moves: [] };
  }
  const [transactions, moves] = await Promise.all([
    unwrap<TransactionRow>(
      client
        .from("transactions")
        .select("id, kind, week, occurred_at, team_ids, faab_moves, waiver_bid")
        .in("id", ids),
      "transactions",
    ),
    unwrap<TransactionMoveRow>(
      client
        .from("transaction_moves")
        .select("transaction_id, sleeper_player_id, team_id, action")
        .in("transaction_id", ids),
      "transaction_moves",
    ),
  ]);
  return { transactions, moves };
}

/** Every week's score rows for the season: one per team per week, each a nine-entry map. */
export function fetchSeasonScores(
  client: BoardClient,
  seasonId: number,
): Promise<SeasonScoreRow[]> {
  return unwrap<SeasonScoreRow>(
    client
      .from("team_week_scores")
      .select("week, team_id, players_points")
      .eq("season_id", seasonId),
    "team_week_scores",
  );
}
