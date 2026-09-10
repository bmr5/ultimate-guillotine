import {
  auctionContext,
  auctionContextLine,
  indexDraftPicks,
} from "@/board/derive/draft";
import { UNKNOWN_OWNER } from "@/board/derive/join";
import type { DraftPickRow, PlayerRow } from "@/board/fetchers";
import type { BoardTeam, RosterPlayer } from "@/board/types";
import type { CatalogTrade } from "@/history/types";

import type {
  SeasonScoreRow,
  TransactionMoveRow,
  TransactionRow,
} from "../fetchers";
import { buildJourney, type JourneyEntry } from "./journey";
import { seasonPoints, type SeasonPoints } from "./points";

export interface PlayerCardInput {
  sleeperPlayerId: string;
  season: number;
  teams: BoardTeam[];
  draftPicks: DraftPickRow[];
  memberIdByTeamId: ReadonlyMap<number, number>;
  /** The directory row, for a player no roster on the board holds. */
  directory: PlayerRow | null;
  /** Directory rows for the other players the journey names. */
  otherPlayers: PlayerRow[];
  transactions: TransactionRow[];
  moves: TransactionMoveRow[];
  seasonScores: SeasonScoreRow[];
  registered: CatalogTrade[];
}

export type CardNumbers =
  | {
      rostered: true;
      projected: number | null;
      live: number | null;
      season: SeasonPoints;
    }
  | { rostered: false; season: SeasonPoints };

export interface CardDraft {
  amount: number;
  pickNo: number;
  ownerName: string;
  contextLine: string;
  /** True when the team that drafted him is the one holding him now. */
  stillHere: boolean;
}

/** Everything the card renders, computed once from the board and the three lazy reads. */
export interface PlayerCardView {
  name: string;
  position: string | null;
  nflTeam: string | null;
  injuryStatus: string | null;
  numbers: CardNumbers;
  /** null reads as undrafted. */
  draft: CardDraft | null;
  journey: JourneyEntry[];
  ownerLabelByTeamId: ReadonlyMap<number, string>;
  playerNameById: ReadonlyMap<string, string>;
}

/** The roster row on the board holding this player, with its team, or null. */
function holder(
  teams: readonly BoardTeam[],
  sleeperPlayerId: string,
): { team: BoardTeam; player: RosterPlayer } | null {
  for (const team of teams) {
    const player = team.roster.find((p) => p.sleeperPlayerId === sleeperPlayerId);
    if (player !== undefined) return { team, player };
  }
  return null;
}

export function buildPlayerCardView(input: PlayerCardInput): PlayerCardView {
  const held = holder(input.teams, input.sleeperPlayerId);
  const ownerLabelByTeamId = new Map(
    input.teams.map((team) => [team.teamId, team.ownerName]),
  );
  const playerNameById = new Map(
    input.otherPlayers.map((row) => [row.sleeper_player_id, row.full_name]),
  );
  const picks = indexDraftPicks(input.draftPicks);
  const pick = picks.get(input.sleeperPlayerId) ?? null;
  const season = seasonPoints(input.seasonScores, input.sleeperPlayerId);

  const name =
    held?.player.fullName ??
    input.directory?.full_name ??
    `Unknown player ${input.sleeperPlayerId}`;

  return {
    name,
    position: held?.player.position ?? input.directory?.position ?? null,
    nflTeam: held?.player.nflTeam ?? input.directory?.team ?? null,
    injuryStatus:
      held?.player.injuryStatus ?? input.directory?.injury_status ?? null,
    numbers:
      held === null
        ? { rostered: false, season }
        : {
            rostered: true,
            projected: held.player.projectedPoints,
            live: held.player.livePoints,
            season,
          },
    draft:
      pick === null
        ? null
        : {
            amount: pick.amount,
            pickNo: pick.pickNo,
            ownerName: ownerLabelByTeamId.get(pick.teamId) ?? UNKNOWN_OWNER,
            contextLine: auctionContextLine(auctionContext(pick, picks.values())),
            stillHere: held !== null && held.team.teamId === pick.teamId,
          },
    journey: buildJourney({
      sleeperPlayerId: input.sleeperPlayerId,
      season: input.season,
      pick,
      transactions: input.transactions,
      moves: input.moves,
      registered: input.registered,
      memberIdByTeamId: input.memberIdByTeamId,
    }),
    ownerLabelByTeamId,
    playerNameById,
  };
}
