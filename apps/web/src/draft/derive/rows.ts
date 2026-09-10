import { resolveOwnerLabel } from "@/board/derive/join";
import type {
  DraftPickRow,
  MemberRow,
  PlayerRow,
  TeamRow,
} from "@/board/fetchers";

export interface DraftRow {
  sleeperPlayerId: string;
  pickNo: number;
  round: number;
  amount: number;
  /** The position Sleeper recorded on the pick, which is what the auction ranked by. */
  position: string | null;
  fullName: string;
  nflTeam: string | null;
  teamId: number;
  ownerName: string;
}

export const DRAFT_SORT_MODES = ["pick", "price", "team"] as const;
export type DraftSortMode = (typeof DRAFT_SORT_MODES)[number];
export const DEFAULT_DRAFT_SORT_MODE: DraftSortMode = "pick";
export const DRAFT_SORT_LABELS: Record<DraftSortMode, string> = {
  pick: "Pick order",
  price: "Price",
  team: "By team",
};

export function parseDraftSortMode(
  raw: string | null | undefined,
): DraftSortMode {
  return DRAFT_SORT_MODES.includes(raw as DraftSortMode)
    ? (raw as DraftSortMode)
    : DEFAULT_DRAFT_SORT_MODE;
}

/**
 * The league's rule (docs/rules): every unspent auction dollar becomes five FAAB dollars, so the
 * auction budget is the FAAB budget over five. `seasons.waiver_budget` is the only budget the
 * data layer stores.
 */
export const FAAB_PER_DRAFT_DOLLAR = 5;

export function draftBudgetPerTeam(waiverBudget: number | null): number | null {
  return waiverBudget === null
    ? null
    : Math.round(waiverBudget / FAAB_PER_DRAFT_DOLLAR);
}

/** Every pick joined to a name, an NFL team and an owner label, in pick order. */
export function draftRows(
  picks: readonly DraftPickRow[],
  teams: readonly TeamRow[],
  members: readonly MemberRow[],
  players: readonly PlayerRow[],
): DraftRow[] {
  const memberById = new Map(members.map((m) => [m.id, m]));
  const teamById = new Map(teams.map((t) => [t.id, t]));
  const playerById = new Map(players.map((p) => [p.sleeper_player_id, p]));
  return [...picks]
    .sort((a, b) => a.pick_no - b.pick_no)
    .map((pick) => {
      const team = teamById.get(pick.team_id);
      const player = playerById.get(pick.sleeper_player_id);
      return {
        sleeperPlayerId: pick.sleeper_player_id,
        pickNo: pick.pick_no,
        round: pick.round,
        amount: pick.amount,
        position: pick.position ?? player?.position ?? null,
        fullName:
          player?.full_name ?? `Unknown player ${pick.sleeper_player_id}`,
        nflTeam: player?.team ?? null,
        teamId: pick.team_id,
        ownerName: resolveOwnerLabel(
          team === undefined ? undefined : memberById.get(team.member_id),
        ),
      };
    });
}

export interface TeamSpend {
  teamId: number;
  ownerName: string;
  picks: number;
  spent: number;
  /** null when the budget is unknown. */
  unspent: number | null;
  /** What the unspent dollars became, by `FAAB_PER_DRAFT_DOLLAR`; null with `unspent`. */
  faab: number | null;
}

/** Each team's auction, in spend order, then owner label. */
export function teamSpend(
  rows: readonly DraftRow[],
  budgetPerTeam: number | null,
): TeamSpend[] {
  const byTeam = new Map<number, TeamSpend>();
  for (const row of rows) {
    const entry = byTeam.get(row.teamId) ?? {
      teamId: row.teamId,
      ownerName: row.ownerName,
      picks: 0,
      spent: 0,
      unspent: null,
      faab: null,
    };
    entry.picks += 1;
    entry.spent += row.amount;
    byTeam.set(row.teamId, entry);
  }
  const spends = [...byTeam.values()].map((entry) => {
    if (budgetPerTeam === null) return entry;
    const unspent = Math.max(0, budgetPerTeam - entry.spent);
    return { ...entry, unspent, faab: unspent * FAAB_PER_DRAFT_DOLLAR };
  });
  return spends.sort(
    (a, b) =>
      b.spent - a.spent ||
      a.ownerName.localeCompare(b.ownerName) ||
      a.teamId - b.teamId,
  );
}

/** Sorts a copy: pick order, price descending (ties by pick), or grouped by team in spend order. */
export function sortDraftRows(
  rows: readonly DraftRow[],
  mode: DraftSortMode,
): DraftRow[] {
  const copy = [...rows];
  if (mode === "price") {
    return copy.sort((a, b) => b.amount - a.amount || a.pickNo - b.pickNo);
  }
  if (mode === "team") {
    const order = new Map(
      teamSpend(rows, null).map((spend, index) => [spend.teamId, index]),
    );
    return copy.sort(
      (a, b) =>
        (order.get(a.teamId) ?? 0) - (order.get(b.teamId) ?? 0) ||
        b.amount - a.amount ||
        a.pickNo - b.pickNo,
    );
  }
  return copy.sort((a, b) => a.pickNo - b.pickNo);
}

export interface DraftSummary {
  pickCount: number;
  spent: number;
  /** The mean price to the dollar, or null with no picks. */
  average: number | null;
}

export function draftSummary(rows: readonly DraftRow[]): DraftSummary {
  const spent = rows.reduce((sum, row) => sum + row.amount, 0);
  return {
    pickCount: rows.length,
    spent,
    average: rows.length === 0 ? null : Math.round(spent / rows.length),
  };
}
