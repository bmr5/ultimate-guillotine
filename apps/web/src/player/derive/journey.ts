import type { DraftPickInfo, FaabMoveEntry } from "@/board/types";
import type { CatalogTrade } from "@/history/types";

import type { TransactionMoveRow, TransactionRow } from "../fetchers";

/** The registered trade a Sleeper trade matched, or one with no counterpart. */
export interface RegisteredLink {
  key: string;
  tradeCode: string;
  announcement: string | null;
  rescinded: boolean;
}

export interface OtherPlayerMove {
  sleeperPlayerId: string;
  fromTeamId: number | null;
  toTeamId: number | null;
}

export interface FaabMove {
  amount: number;
  fromTeamId: number;
  toTeamId: number;
}

export type JourneyEntry =
  | {
      kind: "drafted";
      key: string;
      at: string;
      week: null;
      teamId: number;
      amount: number;
      pickNo: number;
    }
  | {
      kind: "traded";
      key: string;
      at: string;
      week: number;
      fromTeamId: number | null;
      toTeamId: number | null;
      others: OtherPlayerMove[];
      faab: FaabMove[];
      registered: RegisteredLink | null;
    }
  | { kind: "dropped"; key: string; at: string; week: number; teamId: number }
  | {
      kind: "claimed";
      key: string;
      at: string;
      week: number;
      teamId: number;
      bid: number | null;
    }
  | { kind: "added"; key: string; at: string; week: number; teamId: number }
  | {
      kind: "commissioner";
      key: string;
      at: string;
      week: number;
      teamId: number;
      action: "add" | "drop";
    }
  | {
      kind: "announced";
      key: string;
      at: string;
      week: number | null;
      registered: RegisteredLink;
    };

export interface JourneyInput {
  sleeperPlayerId: string;
  /** The board's season year; registered trades from any other are ignored. */
  season: number;
  pick: DraftPickInfo | null;
  transactions: TransactionRow[];
  /** Every move of every transaction in `transactions`, this player's and the others'. */
  moves: TransactionMoveRow[];
  registered: CatalogTrade[];
  memberIdByTeamId: ReadonlyMap<number, number>;
}

/** How far apart a Sleeper trade and its announcement may be and still be the same deal. */
export const MATCH_WINDOW_MS = 72 * 60 * 60 * 1000;

function link(trade: CatalogTrade): RegisteredLink {
  return {
    key: trade.key,
    tradeCode: trade.sourceLabel,
    announcement: trade.announcement,
    rescinded: trade.rescinded,
  };
}

function sameSet(a: readonly number[], b: readonly number[]): boolean {
  const left = new Set(a);
  const right = new Set(b);
  if (left.size !== right.size) return false;
  for (const value of left) if (!right.has(value)) return false;
  return true;
}

/** The instant a registered trade was announced, or null when it cannot be read. */
function registeredAt(trade: CatalogTrade): number | null {
  if (trade.registeredAt === null) return null;
  const at = Date.parse(trade.registeredAt);
  return Number.isFinite(at) ? at : null;
}

interface SleeperTradeSummary {
  id: number;
  occurredAt: number;
  memberIds: number[];
}

/**
 * Pair Sleeper trades with registered ones: same owners, announced within the window, nearest
 * wins, each registered trade at most once. A registered trade with a party the directory
 * cannot name never matches — its owner set is unknowable.
 */
export function matchRegisteredTrades(
  trades: readonly SleeperTradeSummary[],
  registered: readonly CatalogTrade[],
): Map<number, CatalogTrade> {
  const candidates: {
    transactionId: number;
    trade: CatalogTrade;
    distance: number;
  }[] = [];
  for (const trade of registered) {
    if (trade.parties.some((party) => !party.resolved)) continue;
    if (trade.parties.length !== trade.partyCount) continue;
    const announced = registeredAt(trade);
    if (announced === null) continue;
    const memberIds = trade.parties.map((party) => party.memberId);
    for (const sleeper of trades) {
      if (!sameSet(sleeper.memberIds, memberIds)) continue;
      const distance = Math.abs(sleeper.occurredAt - announced);
      if (distance > MATCH_WINDOW_MS) continue;
      candidates.push({ transactionId: sleeper.id, trade, distance });
    }
  }
  candidates.sort((a, b) => a.distance - b.distance);
  const matched = new Map<number, CatalogTrade>();
  const used = new Set<string>();
  for (const candidate of candidates) {
    if (matched.has(candidate.transactionId) || used.has(candidate.trade.key)) {
      continue;
    }
    matched.set(candidate.transactionId, candidate.trade);
    used.add(candidate.trade.key);
  }
  return matched;
}

/**
 * `transactions.faab_moves` is jsonb: typed by its producer, narrowed here because a stored row
 * is data some earlier build wrote that no `tsc` run over this one can vouch for.
 */
function faabMoves(entries: FaabMoveEntry[]): FaabMove[] {
  const value: unknown = entries;
  if (!Array.isArray(value)) return [];
  return (value as unknown[]).flatMap((entry) => {
    if (typeof entry !== "object" || entry === null) return [];
    const move = entry as Record<string, unknown>;
    if (
      typeof move.amount !== "number" ||
      typeof move.from_team_id !== "number" ||
      typeof move.to_team_id !== "number"
    ) {
      return [];
    }
    return [
      {
        amount: move.amount,
        fromTeamId: move.from_team_id,
        toTeamId: move.to_team_id,
      },
    ];
  });
}

function namesPlayer(trade: CatalogTrade, sleeperPlayerId: string): boolean {
  return trade.assets.some(
    (asset) => asset.kind === "player" && asset.playerId === sleeperPlayerId,
  );
}

/**
 * The player's season as an ordered list: drafted, then every transaction he was in, with the
 * league's own announcement attached where a registered trade matches, and the announcements
 * no Sleeper trade explains kept as entries of their own.
 */
export function buildJourney(input: JourneyInput): JourneyEntry[] {
  const entries: JourneyEntry[] = [];
  if (input.pick !== null) {
    entries.push({
      kind: "drafted",
      key: "draft",
      at: input.pick.draftedAt,
      week: null,
      teamId: input.pick.teamId,
      amount: input.pick.amount,
      pickNo: input.pick.pickNo,
    });
  }

  const movesByTransaction = new Map<number, TransactionMoveRow[]>();
  for (const move of input.moves) {
    const list = movesByTransaction.get(move.transaction_id);
    if (list === undefined) movesByTransaction.set(move.transaction_id, [move]);
    else list.push(move);
  }

  const mine = (id: number, action: "add" | "drop") =>
    movesByTransaction
      .get(id)
      ?.find(
        (m) => m.sleeper_player_id === input.sleeperPlayerId && m.action === action,
      ) ?? null;

  const sleeperTrades: SleeperTradeSummary[] = input.transactions
    .filter((t) => t.kind === "trade")
    .map((t) => ({
      id: t.id,
      occurredAt: Date.parse(t.occurred_at),
      memberIds: t.team_ids
        .map((teamId) => input.memberIdByTeamId.get(teamId))
        .filter((id): id is number => id !== undefined),
    }))
    .filter((t) => Number.isFinite(t.occurredAt));

  const inSeason = input.registered.filter(
    (trade) =>
      trade.season === input.season && namesPlayer(trade, input.sleeperPlayerId),
  );
  const matched = matchRegisteredTrades(sleeperTrades, inSeason);
  const matchedKeys = new Set([...matched.values()].map((trade) => trade.key));

  for (const t of input.transactions) {
    const added = mine(t.id, "add");
    const dropped = mine(t.id, "drop");
    if (added === null && dropped === null) continue;
    const key = `tx:${t.id}`;
    if (t.kind === "trade") {
      const others = new Map<string, OtherPlayerMove>();
      for (const move of movesByTransaction.get(t.id) ?? []) {
        if (move.sleeper_player_id === input.sleeperPlayerId) continue;
        const other = others.get(move.sleeper_player_id) ?? {
          sleeperPlayerId: move.sleeper_player_id,
          fromTeamId: null,
          toTeamId: null,
        };
        if (move.action === "add") other.toTeamId = move.team_id;
        else other.fromTeamId = move.team_id;
        others.set(move.sleeper_player_id, other);
      }
      const registeredTrade = matched.get(t.id);
      entries.push({
        kind: "traded",
        key,
        at: t.occurred_at,
        week: t.week,
        fromTeamId: dropped?.team_id ?? null,
        toTeamId: added?.team_id ?? null,
        others: [...others.values()],
        faab: faabMoves(t.faab_moves),
        registered: registeredTrade === undefined ? null : link(registeredTrade),
      });
    } else if (t.kind === "waiver") {
      if (added !== null) {
        entries.push({
          kind: "claimed",
          key,
          at: t.occurred_at,
          week: t.week,
          teamId: added.team_id,
          bid: t.waiver_bid,
        });
      } else if (dropped !== null) {
        entries.push({
          kind: "dropped",
          key,
          at: t.occurred_at,
          week: t.week,
          teamId: dropped.team_id,
        });
      }
    } else if (t.kind === "free_agent") {
      if (added !== null) {
        entries.push({
          kind: "added",
          key,
          at: t.occurred_at,
          week: t.week,
          teamId: added.team_id,
        });
      } else if (dropped !== null) {
        entries.push({
          kind: "dropped",
          key,
          at: t.occurred_at,
          week: t.week,
          teamId: dropped.team_id,
        });
      }
    } else {
      const move = added ?? dropped;
      if (move !== null) {
        entries.push({
          kind: "commissioner",
          key,
          at: t.occurred_at,
          week: t.week,
          teamId: move.team_id,
          action: added !== null ? "add" : "drop",
        });
      }
    }
  }

  for (const trade of inSeason) {
    if (matchedKeys.has(trade.key) || trade.registeredAt === null) continue;
    entries.push({
      kind: "announced",
      key: `reg:${trade.key}`,
      at: trade.registeredAt,
      week: trade.week,
      registered: link(trade),
    });
  }

  return entries.sort((a, b) => {
    if (a.kind === "drafted" && b.kind !== "drafted") return -1;
    if (b.kind === "drafted" && a.kind !== "drafted") return 1;
    return (
      (Date.parse(a.at) || 0) - (Date.parse(b.at) || 0) ||
      a.key.localeCompare(b.key)
    );
  });
}
