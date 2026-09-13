import type { TableRow } from "../types";

export interface LiveScore {
  rosterId: number;
  points: number;
  playersPoints: Record<string, number>;
  starters: string[];
}

export function parseLiveScores(payload: unknown): LiveScore[] {
  if (!Array.isArray(payload) || !payload.length)
    throw new Error("Live scores unavailable");
  return payload.map((row) => {
    const points =
      typeof row?.custom_points === "number" &&
      Number.isFinite(row.custom_points)
        ? row.custom_points
        : row?.points;
    if (
      !Number.isInteger(row?.roster_id) ||
      typeof points !== "number" ||
      !Number.isFinite(points) ||
      !Array.isArray(row.starters) ||
      !row.starters.every((id: unknown) => typeof id === "string") ||
      !row.players_points ||
      typeof row.players_points !== "object" ||
      Array.isArray(row.players_points)
    ) {
      throw new Error("Incomplete live score data");
    }
    const playersPoints: Record<string, number> = {};
    for (const [id, value] of Object.entries(row.players_points)) {
      if (typeof value === "number" && Number.isFinite(value))
        playersPoints[id] = value;
    }
    return {
      rosterId: row.roster_id,
      points,
      playersPoints,
      starters: row.starters,
    };
  });
}

export interface LiveScoreFeed {
  rows: LiveScore[];
  receivedAt: string;
}

/** Map the league's roster ids onto our team ids, preserving DB fallback rows. */
export function mergeLiveScores(
  saved: TableRow<"team_week_scores">[],
  feed: LiveScoreFeed | undefined,
  teams: Pick<TableRow<"teams">, "id" | "sleeper_roster_id">[],
  seasonId: number,
  week: number,
): TableRow<"team_week_scores">[] {
  if (!feed) return saved;
  const rows = new Map(saved.map((row) => [row.team_id, row]));
  const teamIds = new Map(
    teams.map((team) => [team.sleeper_roster_id, team.id]),
  );
  for (const live of feed.rows) {
    const id = teamIds.get(live.rosterId);
    if (id === undefined) continue;
    const previous = rows.get(id);
    if (
      previous &&
      Date.parse(previous.synced_at) > Date.parse(feed.receivedAt)
    )
      continue;
    rows.set(id, {
      season_id: seasonId,
      week,
      team_id: id,
      points: live.points,
      players_points: live.playersPoints,
      starters: live.starters,
      synced_at: feed.receivedAt,
    });
  }
  return [...rows.values()];
}
