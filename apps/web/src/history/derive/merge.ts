import type {
  HistoryMemberRow,
  RegisteredRevisionRow,
  RegisteredTradeRow,
  TradeCatalogRow,
} from "../fetchers";
import type { CatalogTrade, TradeAsset, TradeParty } from "../types";
import { isRecord } from "./json";
import { FORMER_MANAGER, ownerLabelFor } from "./ownerLabel";

export const CATALOG_SOURCE_LABEL = "catalog";

/** A `jsonb` string field, or `null` when it is absent or some other type. */
function optionalText(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

/**
 * A party *index* written into the document — a position in the trade's own `parties` array, so
 * a finite integer or nothing. `2.5`, `NaN` and `"1"` are all "no index".
 */
function optionalIndex(value: unknown): number | null {
  return Number.isInteger(value) ? (value as number) : null;
}

/**
 * A trade party, named where the directory can name one. A member id it does not carry is still
 * a party to the deal, so it keeps its place on the card under `FORMER_MANAGER` rather than
 * being dropped — the row would otherwise read as a smaller trade than it was.
 *
 * `resolved` records which of the two happened, so a caller can count the parties it cannot
 * name without reading the stand-in label back out of the field meant for a name.
 */
function tradeParty(memberId: number, members: HistoryMemberRow[]): TradeParty {
  const label = ownerLabelFor(memberId, members);
  return {
    memberId,
    label: label ?? FORMER_MANAGER,
    resolved: label !== null,
  };
}

function catalogAssets(value: unknown): TradeAsset[] {
  if (!Array.isArray(value)) return [];
  const assets: TradeAsset[] = [];
  for (const entry of value as unknown[]) {
    if (!isRecord(entry)) continue;
    if (entry.kind === "player") {
      assets.push({
        kind: "player",
        playerId: optionalText(entry.sleeper_player_id),
        // A missing or non-string name is the empty string, never `undefined`: the type says
        // `string` and `filterTrades` folds it on every keystroke.
        name: optionalText(entry.name) ?? "",
        position: optionalText(entry.position),
        fromParty: optionalIndex(entry.from_party),
        toParty: optionalIndex(entry.to_party),
      });
    } else if (entry.kind === "faab" && typeof entry.amount === "number") {
      assets.push({
        kind: "faab",
        amount: entry.amount,
        fromParty: optionalIndex(entry.from_party),
        toParty: optionalIndex(entry.to_party),
      });
    } else if (entry.kind === "condition" && typeof entry.label === "string") {
      assets.push({ kind: "condition", label: entry.label });
    }
  }
  return assets;
}

export function normalizeCatalogTrade(
  row: TradeCatalogRow,
  members: HistoryMemberRow[],
): CatalogTrade {
  return {
    key: `catalog:${row.id}`,
    season: row.season,
    week: row.week,
    occurredOn: row.occurred_on,
    tradeType: row.trade_type,
    structure: row.structure,
    parties: row.party_member_ids.map((id) => tradeParty(id, members)),
    partyCount: row.party_count,
    assets: catalogAssets(row.assets),
    confidence: row.confidence,
    // `optionalText`, not the field itself, for the reason the asset name below is guarded:
    // a column PostgREST did not return is `undefined`, and `filterTrades` folds this string
    // on every keystroke. The type says `string | null`, so nothing else may say otherwise.
    announcement: optionalText(row.announcement),
    // The catalog is a reading of a spreadsheet: it knows a season and a week, never an
    // instant, so a catalog card is dated by those and this stays null.
    registeredAt: null,
    sourceLabel: CATALOG_SOURCE_LABEL,
    registered: false,
    rescinded: false,
    unresolvedParties: row.unresolved_parties,
  };
}

/**
 * Where a registered asset's counterparty sits in this trade's own party list.
 *
 * `indexOf` answers `-1` for a member id that is not one of the resolved parties — an
 * unresolved counterparty, or a `member_id` the terms document never listed. `-1` is not a
 * party index, so it becomes `null`, which is what the type means by "no known side".
 */
function partyIndex(memberIds: number[], value: unknown): number | null {
  if (typeof value !== "number") return null;
  const index = memberIds.indexOf(value);
  return index === -1 ? null : index;
}

/**
 * Turn a registered trade into the same shape, reading only the fields that are safe.
 *
 * `evidence_excerpt` is one of them now. It is the message the league announced the trade in,
 * the fetcher asks for it under the name `announcement`, and it is carried through to the card
 * by Ben's ruling of 2026-09-10 — one field, named and decided on.
 *
 * Everything else in the document is unchanged. `parties[].display_name` is the bare Sleeper
 * username; `assets[].player_name` is the player as he was typed into the chat and
 * `assets[].description` is the trade as somebody phrased it. All three ride along inside
 * `terms->parties` and `terms->assets` because PostgREST cannot project keys out of a JSON
 * array, and none of them is copied out: below this line the function takes ids and amounts and
 * nothing else, so a future terms shape that adds more prose adds it to a field nobody reads.
 */
export function normalizeRegisteredTrade(
  trade: RegisteredTradeRow,
  revision: RegisteredRevisionRow | undefined,
  members: HistoryMemberRow[],
): CatalogTrade {
  // The optional chain is repeated inside the branch on purpose: `Array.isArray` narrows the
  // property it is handed, not the object the chain started from, so `revision` is still
  // `RegisteredRevisionRow | undefined` here as far as `tsc --strict` is concerned.
  const rawParties = (
    Array.isArray(revision?.parties) ? (revision?.parties as unknown[]) : []
  ).filter(isRecord);
  const memberIds = rawParties
    .map((party) => party.member_id)
    .filter((id): id is number => typeof id === "number");
  const rawAssets = (
    Array.isArray(revision?.assets) ? (revision?.assets as unknown[]) : []
  ).filter(isRecord);

  const assets: TradeAsset[] = [];
  for (const asset of rawAssets) {
    if (asset.kind === "faab" && typeof asset.amount === "number") {
      assets.push({
        kind: "faab",
        amount: asset.amount,
        fromParty: partyIndex(memberIds, asset.from_member_id),
        toParty: partyIndex(memberIds, asset.to_member_id),
      });
    } else if (asset.kind === "player") {
      assets.push({
        kind: "player",
        playerId: optionalText(asset.player_id),
        // `terms.assets[].player_name` is deliberately not read. The Registrar stores the
        // name exactly as it was written in the league chat message (`resolve.py` keeps
        // `asset.player_name` verbatim and only ever *adds* a resolved `player_id`
        // alongside it), so it is chat prose, not a canonical player name, and putting it
        // here would put a chat fragment on a public page. The resolved `playerId` is the
        // safe handle; the page looks the name up from it.
        name: "",
        position: null,
        fromParty: partyIndex(memberIds, asset.from_member_id),
        toParty: partyIndex(memberIds, asset.to_member_id),
      });
    }
  }

  return {
    key: `registered:${trade.id}`,
    season: trade.seasons?.year ?? 0,
    week: revision?.effective_week ?? null,
    occurredOn: null,
    tradeType: revision?.kind ?? "trade",
    structure: `${memberIds.length}-team`,
    parties: memberIds.map((id) => tradeParty(id, members)),
    partyCount: rawParties.length,
    assets,
    confidence: "high",
    announcement: optionalText(revision?.announcement),
    registeredAt: trade.created_at,
    sourceLabel: trade.trade_code,
    registered: true,
    rescinded: trade.status === "rescinded",
    unresolvedParties: rawParties.length - memberIds.length,
  };
}

/**
 * Union the two sources, newest season first.
 *
 * A season with at least one registered trade is the backfill's: its catalog rows are the same
 * deals read by an analyst rather than by the Registrar, so they drop out. The count of dropped
 * rows is returned rather than swallowed — the stats strip says so on the page.
 */
export function mergeTradeSources(
  catalog: TradeCatalogRow[],
  registered: RegisteredTradeRow[],
  revisions: RegisteredRevisionRow[],
  members: HistoryMemberRow[],
): { trades: CatalogTrade[]; replacedByBackfill: number } {
  const registeredSeasons = new Set(
    registered
      .map((trade) => trade.seasons?.year)
      .filter((year): year is number => !!year),
  );
  const revisionById = new Map(
    revisions.map((revision) => [revision.id, revision]),
  );

  const kept = catalog.filter((row) => !registeredSeasons.has(row.season));
  const trades = [
    ...registered.map((trade) =>
      normalizeRegisteredTrade(
        trade,
        trade.current_revision_id === null
          ? undefined
          : revisionById.get(trade.current_revision_id),
        members,
      ),
    ),
    ...kept.map((row) => normalizeCatalogTrade(row, members)),
  ].sort((a, b) => b.season - a.season || (b.week ?? 0) - (a.week ?? 0));

  return { trades, replacedByBackfill: catalog.length - kept.length };
}
