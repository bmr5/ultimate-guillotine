import { describe, expect, it } from "vitest";

import { boardKeys, fingerprintIds } from "./queryKeys";
import {
  backoffDelayMs,
  BOARD_REALTIME_TABLES,
  keysForTable,
  REALTIME_BACKOFF_CAP_MS,
  REALTIME_BACKOFF_JITTER_MAX,
  REALTIME_BACKOFF_JITTER_MIN,
  REALTIME_DEBOUNCE_MS,
  REALTIME_MAX_EVENTS_PER_TABLE,
  REALTIME_MAX_WAIT_MS,
  REALTIME_POLL_MS,
} from "./realtime";

describe("realtime constants", () => {
  it("subscribes only to the five published tables", () => {
    expect([...BOARD_REALTIME_TABLES]).toEqual([
      "roster_holdings",
      "team_season_state",
      "team_week_projections",
      "team_week_scores",
      "nfl_state",
    ]);
  });

  it("uses the spec's timings", () => {
    expect(REALTIME_DEBOUNCE_MS).toBe(750);
    expect(REALTIME_MAX_EVENTS_PER_TABLE).toBe(24);
    expect(REALTIME_POLL_MS).toBe(60_000);
    expect(REALTIME_BACKOFF_CAP_MS).toBe(30_000);
  });

  it("leaves a run of eighteen rows room under the per-table ceiling", () => {
    // Two jobs write eighteen rows each on the same minute boundary through a game window, so
    // the ceiling has to be per table and has to sit clear of a single run rather than on it.
    expect(REALTIME_MAX_EVENTS_PER_TABLE).toBeGreaterThan(18);
  });

  it("forces a flush before a sustained burst can starve the refetch", () => {
    expect(REALTIME_MAX_WAIT_MS).toBeGreaterThan(REALTIME_DEBOUNCE_MS);
    expect(REALTIME_MAX_WAIT_MS).toBe(3_000);
  });
});

describe("backoffDelayMs", () => {
  /** The midpoint of the jitter range, which reproduces the undithered delay exactly. */
  const noJitter = () => 0.5;

  it("doubles from one second and caps at thirty", () => {
    expect(backoffDelayMs(0, noJitter)).toBe(1_000);
    expect(backoffDelayMs(1, noJitter)).toBe(2_000);
    expect(backoffDelayMs(2, noJitter)).toBe(4_000);
    expect(backoffDelayMs(10, noJitter)).toBe(30_000);
  });

  it("scales the delay by the jitter factor so a league does not reconnect in lockstep", () => {
    expect(backoffDelayMs(1, () => 0)).toBe(
      2_000 * REALTIME_BACKOFF_JITTER_MIN,
    );
    // The top of the band is exclusive before rounding, which is why this is not `toBeLessThan`.
    expect(backoffDelayMs(1, () => 0.999_999)).toBeLessThanOrEqual(
      2_000 * REALTIME_BACKOFF_JITTER_MAX,
    );
    expect(backoffDelayMs(1, () => 0.999_999)).toBeGreaterThan(2_000);
  });

  it("keeps the spread at the cap, where a synchronised herd would be worst", () => {
    expect(backoffDelayMs(20, () => 0)).toBe(
      REALTIME_BACKOFF_CAP_MS * REALTIME_BACKOFF_JITTER_MIN,
    );
    expect(backoffDelayMs(20, () => 0.999_999)).toBeGreaterThan(
      REALTIME_BACKOFF_CAP_MS,
    );
  });

  it("uses Math.random by default and stays inside the jittered band", () => {
    for (let index = 0; index < 50; index += 1) {
      const delay = backoffDelayMs(3);
      expect(delay).toBeGreaterThanOrEqual(8_000 * REALTIME_BACKOFF_JITTER_MIN);
      expect(delay).toBeLessThanOrEqual(8_000 * REALTIME_BACKOFF_JITTER_MAX);
    }
  });
});

describe("keysForTable", () => {
  const context = { seasonId: 1, season: 2026, week: 3 };

  it("maps a roster change to rosters and the player projections that hang off them", () => {
    expect(keysForTable("roster_holdings", context)).toEqual([
      boardKeys.rosterHoldings(1),
      boardKeys.playerProjectionsPrefix(2026, 3),
    ]);
  });

  it("leaves the static player directory alone, since its own key tracks the id set", () => {
    // `boardKeys.players` carries a fingerprint of the held ids, so a roster change that alters
    // the set already produces a different key and a fresh fetch; one that only moves a holding
    // between teams leaves the directory correct. Refetching it here would be pure waste — it
    // is the largest request on the board.
    const keys = keysForTable("roster_holdings", context);
    expect(keys.some((key) => key[1] === "players")).toBe(false);
  });

  it("invalidates the projections branch by prefix, since the fingerprint is not known here", () => {
    const [, projectionsKey] = keysForTable("roster_holdings", context);
    const fingerprint = fingerprintIds(["4034", "6794"]);
    // A prefix of the concrete key is what invalidateQueries needs to reach every cache entry
    // for the week regardless of which held-id set produced it.
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

  it("maps a score change to the week's score query and nothing else", () => {
    // The reason the table is published: Ben asked for the score to be realtime. A run writes
    // one row per team, and eighteen events debounce into this one invalidation rather than
    // dragging the whole board — including the id-fingerprinted player directory — with them.
    expect(keysForTable("team_week_scores", context)).toEqual([
      boardKeys.teamWeekScores(1, 3),
    ]);
  });

  it("falls back to the whole board for a score event before the context resolves", () => {
    expect(
      keysForTable("team_week_scores", {
        seasonId: null,
        season: null,
        week: null,
      }),
    ).toEqual([boardKeys.all]);
  });

  it("maps an nfl_state change to the nfl_state query alone", () => {
    // The heartbeat rewrites this row every few minutes without changing the season or the
    // week, so invalidating the whole board here refetched every query — the id-fingerprinted
    // player directory included — for nothing. A real rollover re-keys the dependent queries
    // by itself, since they are keyed on the season id, the season and the week.
    expect(keysForTable("nfl_state", context)).toEqual([boardKeys.nflState()]);
    expect(keysForTable("nfl_state", context)).not.toContainEqual(
      boardKeys.all,
    );
  });

  it("still falls back to the whole board for an nfl_state event before the context resolves", () => {
    // The first nfl_state row is what resolves the context, so there is no narrower key yet.
    expect(
      keysForTable("nfl_state", { seasonId: null, season: null, week: null }),
    ).toEqual([boardKeys.all]);
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
