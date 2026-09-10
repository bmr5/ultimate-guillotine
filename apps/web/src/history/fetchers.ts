import type { PostgrestClient } from "@supabase/postgrest-js";

import { chunkIds } from "@/board/fetchers";
import type { Database, TableRow } from "@/board/types";

export type HistoryClient = PostgrestClient<Database>;

/**
 * Both row types name exactly the columns their select asks for, and no more — the rule
 * `HistoryPlayerRow` states below. `trade_catalog.source` says whether the analyst read the
 * deal from the Registrar or from the chat, which the page answers from `sourceLabel` instead;
 * `trade_catalog.faab_total` is the analyst's total for a deal, which no longer reaches a card
 * (Ben's ruling of 2026-09-09: "because of the dynamic nature of many deals it's most likely
 * not useful to include the FAAB number here"); `season_results.unresolved_names` is a loader
 * diagnostic no page renders. None is requested, so none is in the type: a field the fetch
 * never returns must not typecheck.
 */
export type TradeCatalogRow = Omit<
  TableRow<"trade_catalog">,
  "source" | "faab_total"
>;
export type SeasonResultRow = Omit<
  TableRow<"season_results">,
  "unresolved_names"
>;
export type HistoryMemberRow = Pick<
  TableRow<"members">,
  "id" | "sleeper_display_name" | "nickname"
>;

/**
 * The player directory row `/trades` needs, and no more.
 *
 * A `Pick` of its own rather than the board's `PlayerRow`, which also carries `team`: the type
 * has to name exactly the columns the select asks for, and `team` — the player's *current* NFL
 * club — answers nothing about a trade made three seasons ago.
 */
export type HistoryPlayerRow = Pick<
  TableRow<"players">,
  "sleeper_player_id" | "full_name" | "position"
>;

/** A registered trade with its season year embedded; `public.trades` has no year column. */
export interface RegisteredTradeRow {
  id: number;
  /**
   * When the Registrar recorded the trade — the one instant these rows carry.
   *
   * A registered card is dated by this rather than by its season and effective week, per Ben's
   * ruling of 2026-09-09 that a card logs "the date and time". `trade_revisions.created_at`
   * would date the *current revision* instead, which moves every time a deal is amended, so the
   * card would silently re-date itself; the trade's own stamp is when the deal was logged and
   * does not move.
   */
  created_at: string;
  /** When the alert was posted in the chat; null for rows logged before it was recorded. */
  announced_at: string | null;
  trade_code: string;
  status: "accepted" | "rescinded";
  current_revision_id: number | null;
  seasons: { year: number } | null;
}

/**
 * One current revision, read as JSON paths rather than as the whole `terms` document.
 *
 * `terms.evidence_excerpt` is now requested, as `announcement`. It is the message the Registrar
 * quoted when it recorded the trade — the league announcing its own deal — and Ben's ruling of
 * 2026-09-10 is that the cards are unreadable without it. That is a decision about one field,
 * taken once, and it is why this doc comment is not the one it replaced: the excerpt is shown on
 * purpose, and `announcement` is the name it is shown under so nothing downstream has to know
 * where it came from.
 *
 * It changes nothing about the rest of the document. `terms.parties[].display_name` is the bare
 * Sleeper username and `terms.assets[].player_name` / `description` are the wording of the chat
 * message itself, and all three are still dropped by `normalizeRegisteredTrade`
 * (src/history/derive/merge.ts) rather than merely unrequested — PostgREST cannot project keys
 * out of a JSON array, so `terms->parties` and `terms->assets` still carry them in the payload.
 * Nothing may hand a raw parties or assets object to a component.
 */
export interface RegisteredRevisionRow {
  id: number;
  trade_id: number;
  effective_week: number | null;
  kind: string | null;
  /** `terms.evidence_excerpt`: the league's own announcement, or null when there is none. */
  announcement: string | null;
  parties: unknown;
  assets: unknown;
}

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

/**
 * One string literal rather than a concatenation on purpose: postgrest-js parses the select
 * list at the type level, and `"a, " + "b"` widens to `string`, which makes every row it
 * returns `GenericStringError` and silently costs the fetcher its typed result.
 */
const CATALOG_COLUMNS =
  "id, catalog_id, season, week, occurred_on, trade_type, structure, party_member_ids, party_count, assets, confidence, announcement, unresolved_parties, loaded_at";

/** Also one literal, for the reason `CATALOG_COLUMNS` is. */
const SEASON_RESULT_COLUMNS =
  "id, season, champion_member_id, co_champion_member_id, runner_up_member_id, third_member_id, team_count, eliminations, notes, loaded_at";

export function fetchTradeCatalog(
  client: HistoryClient,
): Promise<TradeCatalogRow[]> {
  return unwrap<TradeCatalogRow>(
    client
      .from("trade_catalog")
      .select(CATALOG_COLUMNS)
      .order("season", { ascending: false }),
    "trade_catalog",
  );
}

export function fetchRegisteredTrades(
  client: HistoryClient,
): Promise<RegisteredTradeRow[]> {
  return unwrap<RegisteredTradeRow>(
    client
      .from("trades")
      .select(
        "id, created_at, announced_at, trade_code, status, current_revision_id, seasons ( year )",
      )
      .order("id", { ascending: false }),
    "trades",
  );
}

export function fetchRegisteredRevisions(
  client: HistoryClient,
): Promise<RegisteredRevisionRow[]> {
  return unwrap<RegisteredRevisionRow>(
    client
      .from("trade_revisions")
      .select(
        "id, trade_id, effective_week, kind:terms->>kind, announcement:terms->>evidence_excerpt, parties:terms->parties, assets:terms->assets",
      ),
    "trade_revisions",
  );
}

export function fetchSeasonResults(
  client: HistoryClient,
): Promise<SeasonResultRow[]> {
  return unwrap<SeasonResultRow>(
    client
      .from("season_results")
      .select(SEASON_RESULT_COLUMNS)
      .order("season", { ascending: false }),
    "season_results",
  );
}

/**
 * The player directory rows the trades on screen actually reference, and no others.
 *
 * A registered asset carries a resolved `player_id` and nothing else the page may render —
 * `terms.assets[].player_name` is the name as it was typed into the league chat and is
 * deliberately dropped by `normalizeRegisteredTrade` — so the name and the position have to come
 * from `public.players`, which is Sleeper's own directory. `active` is not filtered on: a trade
 * from 2022 names players who have since retired, and Sleeper's dump drops them, so the sync
 * keeps their rows with `active = false` precisely so history can still be read.
 *
 * The ids are passed in and chunked rather than the table being read whole, for the reason the
 * board chunks its own: `public.players` holds every player Sleeper has ever dumped, PostgREST
 * caps rows silently, and a truncated response does not fail — it renames a traded player
 * "Unlisted player". One request per `IN_CHUNK_SIZE` ids, in parallel, merged in id order.
 */
export async function fetchHistoryPlayers(
  client: HistoryClient,
  sleeperPlayerIds: readonly string[],
): Promise<HistoryPlayerRow[]> {
  if (sleeperPlayerIds.length === 0) {
    return [];
  }
  const batches = await Promise.all(
    chunkIds(sleeperPlayerIds).map((ids) =>
      unwrap<HistoryPlayerRow>(
        client
          .from("players")
          .select("sleeper_player_id, full_name, position")
          .in("sleeper_player_id", ids),
        "players",
      ),
    ),
  );
  return batches.flat();
}

export function fetchHistoryMembers(
  client: HistoryClient,
): Promise<HistoryMemberRow[]> {
  return unwrap<HistoryMemberRow>(
    client.from("members").select("id, sleeper_display_name, nickname"),
    "members",
  );
}
