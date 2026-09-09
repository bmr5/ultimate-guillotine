import { describe, expect, it } from "vitest";

import { boardKeys, fingerprintIds } from "./queryKeys";
import {
  backoffDelayMs,
  BOARD_REALTIME_TABLES,
  keysForTable,
  REALTIME_BACKOFF_CAP_MS,
  REALTIME_DEBOUNCE_MS,
  REALTIME_MAX_EVENTS_PER_BURST,
  REALTIME_MAX_WAIT_MS,
  REALTIME_POLL_MS,
} from "./realtime";

describe("realtime constants", () => {
  it("subscribes only to the four published tables", () => {
    expect([...BOARD_REALTIME_TABLES]).toEqual([
      "roster_holdings",
      "team_season_state",
      "team_week_projections",
      "nfl_state",
    ]);
  });

  it("uses the spec's timings", () => {
    expect(REALTIME_DEBOUNCE_MS).toBe(750);
    expect(REALTIME_MAX_EVENTS_PER_BURST).toBe(18);
    expect(REALTIME_POLL_MS).toBe(60_000);
    expect(REALTIME_BACKOFF_CAP_MS).toBe(30_000);
  });

  it("forces a flush before a sustained burst can starve the refetch", () => {
    expect(REALTIME_MAX_WAIT_MS).toBeGreaterThan(REALTIME_DEBOUNCE_MS);
    expect(REALTIME_MAX_WAIT_MS).toBe(3_000);
  });
});

describe("backoffDelayMs", () => {
  it("doubles from one second and caps at thirty", () => {
    expect(backoffDelayMs(0)).toBe(1_000);
    expect(backoffDelayMs(1)).toBe(2_000);
    expect(backoffDelayMs(2)).toBe(4_000);
    expect(backoffDelayMs(10)).toBe(30_000);
  });
});

describe("keysForTable", () => {
  const context = { seasonId: 1, season: 2026, week: 3 };

  it("maps a roster change to rosters and the player projections that hang off them", () => {
    expect(keysForTable("roster_holdings", context)).toEqual([
      boardKeys.rosterHoldings(1),
      ["board", "players", 1],
      ["board", "player_projections", 2026, 3],
    ]);
  });

  it("invalidates the player branches by prefix, since the fingerprint is not known here", () => {
    const [, playersKey, projectionsKey] = keysForTable("roster_holdings", context);
    const fingerprint = fingerprintIds(["4034", "6794"]);
    // A prefix of the concrete key is what invalidateQueries needs to reach every cache entry
    // for the season regardless of which held-id set produced it.
    expect(boardKeys.players(1, fingerprint)).toEqual([...playersKey, fingerprint]);
    expect(boardKeys.playerProjections(2026, 3, fingerprint)).toEqual([
      ...projectionsKey,
      fingerprint,
    ]);
  });

  it("maps a state change to the state query and the frozen rosters", () => {
    // The board does not subscribe to `final_rosters` (Spec issue 11), so the elimination
    // that writes a snapshot reaches it as the team_season_state change that flips
    // is_eliminated, in the same transaction.
    expect(keysForTable("team_season_state", context)).toEqual([
      boardKeys.teamSeasonState(1),
      boardKeys.finalRosters(1),
    ]);
  });

  it("maps a projection change to the week's projection query", () => {
    expect(keysForTable("team_week_projections", context)).toEqual([
      boardKeys.teamWeekProjections(1, 3),
    ]);
  });

  it("maps an nfl_state change to the whole board, since the week may have moved", () => {
    expect(keysForTable("nfl_state", context)).toEqual([boardKeys.all]);
  });

  it("falls back to the whole board when the context is not resolved yet", () => {
    expect(
      keysForTable("team_week_projections", {
        seasonId: null,
        season: null,
        week: null,
      }),
    ).toEqual([boardKeys.all]);
  });
});
