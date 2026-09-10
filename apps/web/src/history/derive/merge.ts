import { resolveOwnerLabel } from "@/board/derive/join";

import type {
  HistoryMemberRow,
  RegisteredRevisionRow,
  RegisteredTradeRow,
  TradeCatalogRow,
} from "../fetchers";
import type { CatalogTrade, TradeAsset, TradeParty } from "../types";

export const CATALOG_SOURCE_LABEL = "catalog";

function labelFor(memberId: number, members: HistoryMemberRow[]): TradeParty {
  // `resolveOwnerLabel` takes `OwnerLabelSource | undefined` and answers "Unknown owner" for a
  // member it cannot label, so `find` returning undefined is already the right input.
  return {
    memberId,
    label: resolveOwnerLabel(members.find((m) => m.id === memberId)),
  };
}

function catalogAssets(value: unknown): TradeAsset[] {
  if (!Array.isArray(value)) return [];
  const assets: TradeAsset[] = [];
  for (const entry of value as Record<string, unknown>[]) {
    if (entry.kind === "player") {
      assets.push({
        kind: "player",
        playerId: (entry.sleeper_player_id as string) ?? null,
        name: (entry.name as string) ?? "",
        position: (entry.position as string) ?? null,
        fromParty: (entry.from_party as number) ?? null,
        toParty: (entry.to_party as number) ?? null,
      });
    } else if (entry.kind === "faab" && typeof entry.amount === "number") {
      assets.push({
        kind: "faab",
        amount: entry.amount,
        fromParty: (entry.from_party as number) ?? null,
        toParty: (entry.to_party as number) ?? null,
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
    parties: row.party_member_ids.map((id) => labelFor(id, members)),
    partyCount: row.party_count,
    assets: catalogAssets(row.assets),
    faabTotal: row.faab_total,
    confidence: row.confidence,
    sourceLabel: CATALOG_SOURCE_LABEL,
    registered: false,
    rescinded: false,
    unresolvedParties: row.unresolved_parties,
  };
}

/**
 * Turn a registered trade into the same shape, reading only the fields that are safe.
 *
 * The revision's `terms` document also holds `evidence_excerpt` — verbatim league chat — and
 * `parties[].display_name`, the bare Sleeper username. Neither is read here, and the fetcher
 * never requests them. `assets[].description` and `assets[].player_name` are requested, because
 * they ride along inside `terms->assets`, but neither is copied out: this function takes ids and
 * amounts and nothing else, so no wording from the chat can reach the page even if a future
 * terms shape adds more prose.
 */
export function normalizeRegisteredTrade(
  trade: RegisteredTradeRow,
  revision: RegisteredRevisionRow | undefined,
  members: HistoryMemberRow[],
): CatalogTrade {
  // The optional chain is repeated inside the branch on purpose: `Array.isArray` narrows the
  // property it is handed, not the object the chain started from, so `revision` is still
  // `RegisteredRevisionRow | undefined` here as far as `tsc --strict` is concerned.
  const rawParties = Array.isArray(revision?.parties)
    ? (revision?.parties as { member_id?: number }[])
    : [];
  const memberIds = rawParties
    .map((party) => party.member_id)
    .filter((id): id is number => typeof id === "number");
  const rawAssets = Array.isArray(revision?.assets)
    ? (revision?.assets as Record<string, unknown>[])
    : [];

  const assets: TradeAsset[] = [];
  let faabTotal: number | null = null;
  for (const asset of rawAssets) {
    if (asset.kind === "faab" && typeof asset.amount === "number") {
      faabTotal = (faabTotal ?? 0) + asset.amount;
      assets.push({
        kind: "faab",
        amount: asset.amount,
        fromParty: memberIds.indexOf(asset.from_member_id as number),
        toParty: memberIds.indexOf(asset.to_member_id as number),
      });
    } else if (asset.kind === "player") {
      assets.push({
        kind: "player",
        playerId: (asset.player_id as string) ?? null,
        // `terms.assets[].player_name` is deliberately not read. The Registrar stores the
        // name exactly as it was written in the league chat message (`resolve.py` keeps
        // `asset.player_name` verbatim and only ever *adds* a resolved `player_id`
        // alongside it), so it is chat prose, not a canonical player name, and putting it
        // here would put a chat fragment on a public page. The resolved `playerId` is the
        // safe handle; the page looks the name up from it.
        name: "",
        position: null,
        fromParty: memberIds.indexOf(asset.from_member_id as number),
        toParty: memberIds.indexOf(asset.to_member_id as number),
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
    parties: memberIds.map((id) => labelFor(id, members)),
    partyCount: rawParties.length,
    assets,
    faabTotal,
    confidence: "high",
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
