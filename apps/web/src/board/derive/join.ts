import type {
  BoardTeam,
  FinalRosterHolding,
  RosterPlayer,
  TableRow,
} from "../types";
import { summarizeWeeklyResults, type WeeklyResultRow } from "./records";
import { orderRoster } from "./roster";

export type OwnerLabelSource = Pick<
  TableRow<"members">,
  "sleeper_display_name" | "nickname"
>;

/**
 * Ben's decision 4: the nickname from `public.members.nickname` when there is one, otherwise
 * `public.members.sleeper_display_name`. `members.display_name` — the bare Sleeper username —
 * is never a fallback, so a member with neither public label reads as "Unknown owner" rather
 * than leaking a username.
 */
export function resolveOwnerLabel(member: OwnerLabelSource | undefined): string {
  const nickname = member?.nickname?.trim() ?? "";
  if (nickname !== "") {
    return nickname;
  }
  const sleeperDisplayName = member?.sleeper_display_name?.trim() ?? "";
  if (sleeperDisplayName !== "") {
    return sleeperDisplayName;
  }
  return "Unknown owner";
}

export interface BoardRawData {
  teams: Pick<
    TableRow<"teams">,
    "id" | "member_id" | "sleeper_roster_id" | "team_name"
  >[];
  members: Pick<TableRow<"members">, "id" | "sleeper_display_name" | "nickname">[];
  teamSeasonState: TableRow<"team_season_state">[];
  teamWeekProjections: TableRow<"team_week_projections">[];
  rosterHoldings: Pick<
    TableRow<"roster_holdings">,
    "team_id" | "sleeper_player_id" | "slot" | "slot_index" | "lineup_position"
  >[];
  players: Pick<
    TableRow<"players">,
    "sleeper_player_id" | "full_name" | "position" | "team"
  >[];
  playerProjections: Pick<
    TableRow<"player_projections">,
    "sleeper_player_id" | "league_points"
  >[];
  weeklyResults: WeeklyResultRow[];
  finalRosters: Pick<
    TableRow<"final_rosters">,
    "team_id" | "eliminated_week" | "holdings" | "frozen_at"
  >[];
}

/**
 * `final_rosters.holdings` is jsonb. The producer writes exactly `FinalRosterHolding` entries and
 * the typed `Database` says so, but a snapshot is data at rest that some earlier build wrote, and
 * no `tsc` run over this build can vouch for it. So the shape is checked on the way in. An entry
 * with no usable player id is the only kind dropped — without an id there is nothing to render or
 * to look a player up by. Everything else degrades: an unranked `slot` is passed through for
 * `orderRoster` to fold into the bench, and a non-numeric index or non-string lineup position
 * becomes null rather than reaching the card as a stray value.
 */
function narrowFrozenHoldings(
  holdings: FinalRosterHolding[],
): FinalRosterHolding[] {
  const entries: unknown = holdings;
  if (!Array.isArray(entries)) {
    return [];
  }

  const narrowed: FinalRosterHolding[] = [];
  for (const entry of entries as unknown[]) {
    if (typeof entry !== "object" || entry === null) {
      continue;
    }
    const holding = entry as Partial<FinalRosterHolding>;
    if (
      typeof holding.sleeper_player_id !== "string" ||
      holding.sleeper_player_id === ""
    ) {
      continue;
    }
    narrowed.push({
      sleeper_player_id: holding.sleeper_player_id,
      slot: typeof holding.slot === "string" ? holding.slot : "bench",
      slot_index:
        typeof holding.slot_index === "number" ? holding.slot_index : null,
      lineup_position:
        typeof holding.lineup_position === "string"
          ? holding.lineup_position
          : null,
    });
  }
  return narrowed;
}

export function joinBoardTeams(raw: BoardRawData): BoardTeam[] {
  const memberById = new Map(raw.members.map((m) => [m.id, m]));
  const stateByTeamId = new Map(raw.teamSeasonState.map((s) => [s.team_id, s]));
  const finalRosterByTeamId = new Map(raw.finalRosters.map((f) => [f.team_id, f]));
  const projectionByTeamId = new Map(
    raw.teamWeekProjections.map((p) => [p.team_id, p]),
  );
  const playerById = new Map(raw.players.map((p) => [p.sleeper_player_id, p]));
  const pointsByPlayerId = new Map(
    raw.playerProjections.map((p) => [p.sleeper_player_id, p.league_points]),
  );
  const summaryByTeamId = summarizeWeeklyResults(raw.weeklyResults);

  // roster_holdings has no FK to players on purpose: Sleeper rosters can carry ids the
  // filtered skill-position directory drops. Those still get a row on the board. The same
  // builder serves the frozen final_rosters entries, which have the same four fields.
  const buildRosterPlayer = (holding: FinalRosterHolding): RosterPlayer => {
    const player = playerById.get(holding.sleeper_player_id);
    return {
      sleeperPlayerId: holding.sleeper_player_id,
      fullName: player?.full_name ?? `Unknown player ${holding.sleeper_player_id}`,
      position: player?.position ?? null,
      nflTeam: player?.team ?? null,
      slot: holding.slot,
      slotIndex: holding.slot_index,
      lineupPosition: holding.lineup_position,
      projectedPoints: pointsByPlayerId.get(holding.sleeper_player_id) ?? null,
    };
  };

  const rosterByTeamId = new Map<number, RosterPlayer[]>();
  for (const holding of raw.rosterHoldings) {
    const entry = buildRosterPlayer(holding);
    const existing = rosterByTeamId.get(holding.team_id);
    if (existing === undefined) {
      rosterByTeamId.set(holding.team_id, [entry]);
    } else {
      existing.push(entry);
    }
  }

  return raw.teams.map((team) => {
    const state = stateByTeamId.get(team.id) ?? null;
    const projection = projectionByTeamId.get(team.id) ?? null;
    const summary = summaryByTeamId.get(team.id) ?? null;

    // Ben's decision 3: once a team is eliminated its roster comes from the snapshot taken at
    // elimination. Sleeper's live roster for an eliminated team is unreliable — players get
    // dropped out of it — so live holdings are ignored entirely once a snapshot exists.
    const isEliminated = state?.is_eliminated ?? false;
    const frozen = isEliminated ? (finalRosterByTeamId.get(team.id) ?? null) : null;

    return {
      teamId: team.id,
      teamName: team.team_name,
      ownerName: resolveOwnerLabel(memberById.get(team.member_id)),
      sleeperRosterId: team.sleeper_roster_id,
      projectedPoints: projection === null ? null : projection.projected_points,
      coveragePct: projection === null ? null : projection.coverage_pct,
      // No projection row for the week is as provisional as it gets.
      isProvisional: projection === null ? true : projection.is_provisional,
      projectionComputedAt: projection === null ? null : projection.computed_at,
      faabRemaining: state === null ? null : state.faab_remaining,
      wins: state?.wins ?? 0,
      losses: state?.losses ?? 0,
      ties: state?.ties ?? 0,
      pointsFor: state === null ? (summary?.pointsFor ?? 0) : state.points_for,
      isEliminated,
      eliminatedWeek: state?.eliminated_week ?? frozen?.eliminated_week ?? null,
      eliminationSource: state?.elimination_source ?? null,
      isRosterFrozen: frozen !== null,
      roster:
        frozen === null
          ? orderRoster(rosterByTeamId.get(team.id) ?? [])
          : orderRoster(narrowFrozenHoldings(frozen.holdings).map(buildRosterPlayer)),
    };
  });
}
