import type { GameStatus, WeekSchedule } from "./currentProjection";

export interface LiveGame {
  status: GameStatus;
  remainingFraction: number;
}
export type LiveGames = Record<string, LiveGame>;

const record = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
const teamCode = (code: string) =>
  ({ WSH: "WAS", JAC: "JAX", LA: "LAR" })[code] ?? code;

/** Only accept the requested regular-season slate, never today's unrelated games. */
export function parseLiveGames(
  payload: unknown,
  season: number,
  week: number,
): LiveGames {
  const data = record(payload);
  if (
    record(data.season).year !== season ||
    record(data.season).type !== 2 ||
    record(data.week).number !== week ||
    !Array.isArray(data.events)
  ) {
    throw new Error("Live game clocks unavailable for this week");
  }
  const games: LiveGames = {};
  for (const value of data.events) {
    const event = record(value);
    if (
      record(event.season).year !== season ||
      record(event.season).type !== 2 ||
      record(event.week).number !== week
    )
      continue;
    const state = record(event.status);
    const type = record(state.type);
    let game: LiveGame;
    if (type.completed === true && type.state === "post") {
      game = { status: "done", remainingFraction: 0 };
    } else if (type.state === "pre") {
      game = { status: "remaining", remainingFraction: 1 };
    } else if (
      type.state === "in" &&
      typeof state.period === "number" &&
      Number.isInteger(state.period) &&
      state.period >= 1 &&
      typeof state.clock === "number" &&
      Number.isFinite(state.clock) &&
      state.clock >= 0 &&
      state.clock <= 900
    ) {
      const seconds =
        state.period <= 4
          ? (4 - state.period) * 900 + state.clock
          : Math.min(state.clock, 600);
      game = { status: "live", remainingFraction: seconds / 3600 };
    } else continue;
    const competition = record(
      Array.isArray(event.competitions) ? event.competitions[0] : null,
    );
    if (
      !Array.isArray(competition.competitors) ||
      competition.competitors.length !== 2
    )
      continue;
    const codes = competition.competitors.map(
      (c) => record(record(c).team).abbreviation,
    );
    if (!codes.every((c) => typeof c === "string" && c.length > 0)) continue;
    for (const code of codes) games[teamCode(code as string)] = game;
  }
  if (!Object.keys(games).length)
    throw new Error("Live game clocks unavailable");
  return games;
}

/** A fresh scoreboard can correct the slower schedule's game status. */
export function scheduleWithLiveGames(
  schedule: WeekSchedule | null,
  games: LiveGames | null,
): WeekSchedule | null {
  if (!schedule && !games) return null;
  const result = { ...schedule };
  for (const [team, game] of Object.entries(games ?? {}))
    result[team] = game.status;
  return result;
}
