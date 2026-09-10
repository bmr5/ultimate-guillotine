import type { HistoryPlayerRow } from "../fetchers";
import type { CatalogTrade, TradeAsset } from "../types";

/**
 * What a player asset reads as when the directory cannot name it: the id resolved to nothing, or
 * the Registrar never resolved one at all. Neutral on purpose — the alternative would be the
 * name as it was typed into the league chat, which is exactly what this page does not print.
 */
export const UNLISTED_PLAYER_LABEL = "Unlisted player";

type PlayerAsset = Extract<TradeAsset, { kind: "player" }>;

/**
 * Whether an asset is a player the page cannot name yet.
 *
 * The gate is the empty name and nothing else. A catalog asset arrives already named — that name
 * is the analyst's, curated for display — and must survive untouched; a registered asset arrives
 * with `name: ""` because `normalizeRegisteredTrade` refuses to copy `terms.assets[].player_name`
 * out of the chat-derived terms document.
 */
function needsName(asset: TradeAsset): asset is PlayerAsset {
  return asset.kind === "player" && asset.name.trim() === "";
}

/**
 * Put a name and a position on every player asset that has neither, from `public.players`.
 *
 * Pure, and identity-preserving: a trade with nothing to resolve is returned as it came in, so
 * the memoised list and cards downstream do not re-render when the directory query settles on
 * data that changes nothing. An id the directory does not carry reads as
 * `UNLISTED_PLAYER_LABEL` rather than disappearing — the asset still moved between two owners,
 * and the trade is a truthful record with one line the page cannot name.
 */
export function resolvePlayerNames(
  trades: CatalogTrade[],
  players: HistoryPlayerRow[],
): CatalogTrade[] {
  const byId = new Map(
    players.map((player) => [player.sleeper_player_id, player]),
  );

  return trades.map((trade) => {
    if (!trade.assets.some(needsName)) {
      return trade;
    }
    return {
      ...trade,
      assets: trade.assets.map((asset) => {
        if (!needsName(asset)) {
          return asset;
        }
        const player =
          asset.playerId === null ? undefined : byId.get(asset.playerId);
        if (player === undefined) {
          return { ...asset, name: UNLISTED_PLAYER_LABEL };
        }
        return {
          ...asset,
          name: player.full_name,
          // The asset's own position wins where it has one: a nameless catalog asset can still
          // carry the position the analyst recorded, and that is the position of the player as
          // he was traded, not the one he plays now.
          position: asset.position ?? player.position,
        };
      }),
    };
  });
}
