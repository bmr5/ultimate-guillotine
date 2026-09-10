import type {
  BoardTeam,
  FinalRosterHolding,
  RosterPlayer,
  RosterSlot,
  TableRow,
} from "../types";
import { summarizeWeeklyResults, type WeeklyResultRow } from "./records";
import { orderRoster } from "./roster";

export type OwnerLabelSource = Pick<
  TableRow<"members">,
  "sleeper_display_name" | "nickname"
>;

/** What a member with no public label reads as, here and anywhere else that needs the word. */
export const UNKNOWN_OWNER = "Unknown owner";

/**
 * Ben's decision 4: the nickname from `public.members.nickname` when there is one, otherwise
 * `public.members.sleeper_display_name`. `members.display_name` — the bare Sleeper username —
 * is never a fallback, so a member with neither public label reads as "Unknown owner" rather
 * than leaking a username.
 */
export function resolveOwnerLabel(
  member: OwnerLabelSource | undefined,
): string {
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

/**
 * The eleven flat row sets the board reads, already scoped by the caller.
 *
 * **The caller must pass single-season, single-week rows.** Every join key here is a team id
 * alone: `teamSeasonState`, `teamWeekProjections` and `finalRosters` are each keyed into a `Map`
 * by `team_id`, and `season_id` / `week` are read but never matched on. So a `teamSeasonState`
 * carrying two seasons, or a `teamWeekProjections` carrying two weeks, silently collapses to
 * whichever row for that team came last in the array — not an error, just the wrong number on
 * the card. The query layer (Task 8) filters by `season_id` and, for projections, by `week`
 * before handing rows over; `weeklyResults` is the one exception, since points-for is an
 * aggregate over a season's weeks and Task 3's `summarizeWeeklyResults` folds it.
 */
export interface BoardRawData {
  teams: Pick<
    TableRow<"teams">,
    "id" | "member_id" | "sleeper_roster_id" | "team_name"
  >[];
  members: Pick<
    TableRow<"members">,
    "id" | "sleeper_display_name" | "nickname"
  >[];
  /** One row per team, for one season. */
  teamSeasonState: TableRow<"team_season_state">[];
  /** One row per team, for one season and one week. */
  teamWeekProjections: TableRow<"team_week_projections">[];
  rosterHoldings: Pick<
    TableRow<"roster_holdings">,
    "team_id" | "sleeper_player_id" | "slot" | "slot_index" | "lineup_position"
  >[];
  players: Pick<
    TableRow<"players">,
    "sleeper_player_id" | "full_name" | "position" | "team" | "injury_status"
  >[];
  playerProjections: Pick<
    TableRow<"player_projections">,
    "sleeper_player_id" | "league_points"
  >[];
  /** Every final week of the one season; `summarizeWeeklyResults` folds these per team. */
  weeklyResults: WeeklyResultRow[];
  /** One row per eliminated team, for one season. */
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
 * to look a player up by. A finite number is a usable id: Sleeper's own payloads carry numeric
 * player ids and `JSON.stringify` of one round-trips as a number, so `4046` becomes `"4046"`
 * rather than vanishing; a defence's alphabetic id such as `"SEA"` is already a string and
 * passes through untouched. Everything else degrades: an unranked `slot` is passed through for
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
    const holding = entry as Record<string, unknown>;

    const rawId = holding.sleeper_player_id;
    let sleeperPlayerId = "";
    if (typeof rawId === "string") {
      sleeperPlayerId = rawId;
    } else if (typeof rawId === "number" && Number.isFinite(rawId)) {
      sleeperPlayerId = String(rawId);
    }
    if (sleeperPlayerId === "") {
      continue;
    }

    narrowed.push({
      sleeper_player_id: sleeperPlayerId,
      slot:
        typeof holding.slot === "string"
          ? (holding.slot as RosterSlot)
          : "bench",
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
  const finalRosterByTeamId = new Map(
    raw.finalRosters.map((f) => [f.team_id, f]),
  );
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
      fullName:
        player?.full_name ?? `Unknown player ${holding.sleeper_player_id}`,
      position: player?.position ?? null,
      nflTeam: player?.team ?? null,
      slot: holding.slot,
      slotIndex: holding.slot_index,
      lineupPosition: holding.lineup_position,
      projectedPoints: pointsByPlayerId.get(holding.sleeper_player_id) ?? null,
      // A holding with no directory row carries no status either: `null` is "nothing is
      // known", which is exactly what an unmatched id means, and the card reads it as
      // available rather than inventing an injury.
      injuryStatus: player?.injury_status ?? null,
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
    const snapshot = isEliminated
      ? finalRosterByTeamId.get(team.id) ?? null
      : null;

    // A snapshot that narrows to nothing — written empty, or entirely malformed — carries no
    // roster to show, and an empty card is worse than a stale one. So the team falls back to its
    // live holdings and reads as unfrozen, which is what the card's "frozen" affordance should
    // say: what is on screen is not the snapshot. The snapshot's `eliminated_week` still counts,
    // since that fact does not depend on the holdings surviving.
    const frozenRoster =
      snapshot === null ? [] : narrowFrozenHoldings(snapshot.holdings);
    const isRosterFrozen = frozenRoster.length > 0;

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
      // No wins, losses or ties: the board carries no record at all (Ben's card change 2), and
      // `weekly_results` has no opponent column to derive one from in the first place.
      pointsFor: state === null ? summary?.pointsFor ?? 0 : state.points_for,
      startersProjected:
        projection === null ? null : projection.starters_projected,
      starterSlots: projection === null ? null : projection.starter_slots,
      isEliminated,
      eliminatedWeek:
        state?.eliminated_week ?? snapshot?.eliminated_week ?? null,
      eliminationSource: state?.elimination_source ?? null,
      emptySlots: projection === null ? null : projection.empty_slots,
      isRosterFrozen,
      roster: isRosterFrozen
        ? orderRoster(frozenRoster.map(buildRosterPlayer))
        : orderRoster(rosterByTeamId.get(team.id) ?? []),
    };
  });
}
