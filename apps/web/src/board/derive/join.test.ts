/**
 * The join is Map lookups over plain rows: no DOM, no timers.
 *
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { FinalRosterHolding } from "../types";
import { type BoardRawData, joinBoardTeams, resolveOwnerLabel } from "./join";

const raw = (over: Partial<BoardRawData> = {}): BoardRawData => ({
  teams: [{ id: 7, member_id: 3, sleeper_roster_id: 1, team_name: "The Choppers" }],
  members: [{ id: 3, sleeper_display_name: "benray", nickname: "Ben" }],
  teamSeasonState: [
    {
      season_id: 1,
      team_id: 7,
      faab_budget: 100,
      faab_used: 25,
      faab_remaining: 75,
      wins: 2,
      losses: 1,
      ties: 0,
      points_for: 301.5,
      points_against: 288.25,
      is_eliminated: false,
      eliminated_week: null,
      elimination_source: null,
      state_version: 1,
      synced_at: "2026-09-09T12:00:00Z",
    },
  ],
  teamWeekProjections: [
    {
      season_id: 1,
      team_id: 7,
      week: 3,
      projected_points: 112.4,
      starter_slots: 9,
      filled_slots: 9,
      empty_slots: 0,
      starters_projected: 9,
      missing_projections: 0,
      coverage_pct: 100,
      is_provisional: false,
      computed_at: "2026-09-09T12:00:00Z",
    },
  ],
  rosterHoldings: [
    {
      team_id: 7,
      sleeper_player_id: "4046",
      slot: "starter",
      slot_index: 0,
      lineup_position: "QB",
    },
    {
      team_id: 7,
      sleeper_player_id: "9999",
      slot: "bench",
      slot_index: null,
      lineup_position: null,
    },
  ],
  players: [
    { sleeper_player_id: "4046", full_name: "Patrick Mahomes", position: "QB", team: "KC" },
  ],
  playerProjections: [{ sleeper_player_id: "4046", league_points: 22.6 }],
  weeklyResults: [
    { week: 1, team_id: 7, points: 150.75, is_final: true, state_version: 1 },
    { week: 2, team_id: 7, points: 150.75, is_final: true, state_version: 1 },
  ],
  finalRosters: [],
  ...over,
});

describe("resolveOwnerLabel", () => {
  it("prefers the nickname", () => {
    expect(
      resolveOwnerLabel({ nickname: "Ben", sleeper_display_name: "benray" }),
    ).toBe("Ben");
  });

  it("falls back to the Sleeper display name when there is no nickname", () => {
    expect(
      resolveOwnerLabel({ nickname: null, sleeper_display_name: "benray" }),
    ).toBe("benray");
  });

  it("treats a blank nickname as absent", () => {
    expect(
      resolveOwnerLabel({ nickname: "   ", sleeper_display_name: "benray" }),
    ).toBe("benray");
  });

  it("never falls through to a username, and says so when both are missing", () => {
    expect(resolveOwnerLabel({ nickname: null, sleeper_display_name: null })).toBe(
      "Unknown owner",
    );
    expect(resolveOwnerLabel(undefined)).toBe("Unknown owner");
  });
});

describe("joinBoardTeams", () => {
  it("joins owner, projection, state and roster onto one team", () => {
    const [team] = joinBoardTeams(raw());
    expect(team.teamId).toBe(7);
    expect(team.ownerName).toBe("Ben");
    expect(team.teamName).toBe("The Choppers");
    expect(team.projectedPoints).toBe(112.4);
    expect(team.coveragePct).toBe(100);
    expect(team.isProvisional).toBe(false);
    expect(team.projectionComputedAt).toBe("2026-09-09T12:00:00Z");
    expect(team.faabRemaining).toBe(75);
    expect(team.wins).toBe(2);
    expect(team.losses).toBe(1);
    expect(team.pointsFor).toBe(301.5);
  });

  it("orders the roster and attaches per-player projections", () => {
    const [team] = joinBoardTeams(raw());
    expect(team.roster.map((p) => p.sleeperPlayerId)).toEqual(["4046", "9999"]);
    expect(team.roster[0]).toMatchObject({
      fullName: "Patrick Mahomes",
      position: "QB",
      nflTeam: "KC",
      slot: "starter",
      lineupPosition: "QB",
      projectedPoints: 22.6,
    });
  });

  it("keeps a holding whose player id is not in the filtered player directory", () => {
    const [team] = joinBoardTeams(raw());
    expect(team.roster[1]).toMatchObject({
      sleeperPlayerId: "9999",
      fullName: "Unknown player 9999",
      position: null,
      nflTeam: null,
      projectedPoints: null,
    });
  });

  it("labels the owner by Sleeper display name when the member has no nickname", () => {
    const [team] = joinBoardTeams(
      raw({ members: [{ id: 3, sleeper_display_name: "benray", nickname: null }] }),
    );
    expect(team.ownerName).toBe("benray");
  });

  it("falls back to weekly_results for points for when there is no state row", () => {
    const [team] = joinBoardTeams(raw({ teamSeasonState: [] }));
    expect(team.pointsFor).toBe(301.5);
    expect(team.faabRemaining).toBeNull();
    expect(team.wins).toBe(0);
    expect(team.isEliminated).toBe(false);
  });

  it("treats a team with no projection row as provisional with no number", () => {
    const [team] = joinBoardTeams(raw({ teamWeekProjections: [] }));
    expect(team.projectedPoints).toBeNull();
    expect(team.coveragePct).toBeNull();
    expect(team.isProvisional).toBe(true);
  });

  it("carries elimination state through", () => {
    const base = raw();
    const [team] = joinBoardTeams({
      ...base,
      teamSeasonState: [
        {
          ...base.teamSeasonState[0],
          is_eliminated: true,
          eliminated_week: 4,
          elimination_source: "sleeper_inferred",
        },
      ],
    });
    expect(team.isEliminated).toBe(true);
    expect(team.eliminatedWeek).toBe(4);
    expect(team.eliminationSource).toBe("sleeper_inferred");
  });

  it("shows an eliminated team the frozen snapshot, not its live holdings", () => {
    const base = raw();
    const [team] = joinBoardTeams({
      ...base,
      teamSeasonState: [
        { ...base.teamSeasonState[0], is_eliminated: true, eliminated_week: 4 },
      ],
      // Sleeper has since dropped 4046 and added 5000; the board must ignore that.
      rosterHoldings: [
        {
          team_id: 7,
          sleeper_player_id: "5000",
          slot: "starter",
          slot_index: 0,
          lineup_position: "QB",
        },
      ],
      finalRosters: [
        {
          team_id: 7,
          eliminated_week: 4,
          holdings: [
            {
              sleeper_player_id: "4046",
              slot: "starter",
              slot_index: 0,
              lineup_position: "QB",
            },
          ],
          frozen_at: "2026-10-01T05:00:00Z",
        },
      ],
    });
    expect(team.isRosterFrozen).toBe(true);
    expect(team.roster.map((p) => p.sleeperPlayerId)).toEqual(["4046"]);
    expect(team.roster[0].fullName).toBe("Patrick Mahomes");
  });

  it("takes the eliminated week from the snapshot when the state row lacks it", () => {
    const base = raw();
    const [team] = joinBoardTeams({
      ...base,
      teamSeasonState: [
        { ...base.teamSeasonState[0], is_eliminated: true, eliminated_week: null },
      ],
      finalRosters: [
        { team_id: 7, eliminated_week: 6, holdings: [], frozen_at: "2026-10-15T05:00:00Z" },
      ],
    });
    expect(team.eliminatedWeek).toBe(6);
  });

  it("leaves an eliminated team on live holdings when no snapshot exists yet", () => {
    const base = raw();
    const [team] = joinBoardTeams({
      ...base,
      teamSeasonState: [
        { ...base.teamSeasonState[0], is_eliminated: true, eliminated_week: 4 },
      ],
    });
    expect(team.isRosterFrozen).toBe(false);
    expect(team.roster.map((p) => p.sleeperPlayerId)).toEqual(["4046", "9999"]);
  });

  it("keeps an active team on its live holdings even if a stale snapshot exists", () => {
    const [team] = joinBoardTeams(
      raw({
        finalRosters: [
          { team_id: 7, eliminated_week: 4, holdings: [], frozen_at: "2026-10-01T05:00:00Z" },
        ],
      }),
    );
    expect(team.isRosterFrozen).toBe(false);
    expect(team.roster).toHaveLength(2);
  });

  it("returns an empty board when there are no teams", () => {
    expect(joinBoardTeams(raw({ teams: [] }))).toEqual([]);
  });

  // `final_rosters.holdings` is jsonb written by whichever build froze the snapshot, so the two
  // tests below drive the shape check that stands between that data at rest and a roster row.
  it("drops only the unusable entries from a malformed frozen snapshot", () => {
    const base = raw();
    const [team] = joinBoardTeams({
      ...base,
      teamSeasonState: [
        { ...base.teamSeasonState[0], is_eliminated: true, eliminated_week: 4 },
      ],
      finalRosters: [
        {
          team_id: 7,
          eliminated_week: 4,
          holdings: [
            null,
            { slot: "starter", slot_index: 0, lineup_position: "QB" },
            {
              sleeper_player_id: "4046",
              slot: "starter",
              slot_index: 0,
              lineup_position: "QB",
            },
          ] as unknown as FinalRosterHolding[],
          frozen_at: "2026-10-01T05:00:00Z",
        },
      ],
    });
    expect(team.isRosterFrozen).toBe(true);
    expect(team.roster.map((p) => p.sleeperPlayerId)).toEqual(["4046"]);
  });

  it("keeps a frozen holding whose slot this build does not know", () => {
    const base = raw();
    const [team] = joinBoardTeams({
      ...base,
      teamSeasonState: [
        { ...base.teamSeasonState[0], is_eliminated: true, eliminated_week: 4 },
      ],
      finalRosters: [
        {
          team_id: 7,
          eliminated_week: 4,
          holdings: [
            {
              sleeper_player_id: "4046",
              slot: "practice_squad",
              slot_index: "0",
              lineup_position: 7,
            },
          ] as unknown as FinalRosterHolding[],
          frozen_at: "2026-10-01T05:00:00Z",
        },
      ],
    });
    expect(team.roster).toHaveLength(1);
    expect(team.roster[0]).toMatchObject({
      sleeperPlayerId: "4046",
      fullName: "Patrick Mahomes",
      slot: "practice_squad",
      slotIndex: null,
      lineupPosition: null,
    });
  });

  it("accepts a numeric frozen player id and leaves an alphabetic one alone", () => {
    const base = raw();
    const [team] = joinBoardTeams({
      ...base,
      teamSeasonState: [
        { ...base.teamSeasonState[0], is_eliminated: true, eliminated_week: 4 },
      ],
      finalRosters: [
        {
          team_id: 7,
          eliminated_week: 4,
          holdings: [
            {
              sleeper_player_id: 4046,
              slot: "starter",
              slot_index: 0,
              lineup_position: "QB",
            },
            {
              sleeper_player_id: "SEA",
              slot: "starter",
              slot_index: 1,
              lineup_position: "DEF",
            },
            {
              sleeper_player_id: Number.NaN,
              slot: "bench",
              slot_index: null,
              lineup_position: null,
            },
          ] as unknown as FinalRosterHolding[],
          frozen_at: "2026-10-01T05:00:00Z",
        },
      ],
    });
    // 4046 arrived as a number and still joins the player directory; SEA is a defence's
    // alphabetic id and passes through untouched; a non-finite number has no usable id.
    expect(team.roster.map((p) => p.sleeperPlayerId)).toEqual(["4046", "SEA"]);
    expect(team.roster[0]).toMatchObject({
      fullName: "Patrick Mahomes",
      projectedPoints: 22.6,
    });
    expect(team.roster[1].fullName).toBe("Unknown player SEA");
  });

  it("falls back to live holdings when a snapshot narrows to no roster at all", () => {
    const base = raw();
    const eliminated = {
      ...base,
      teamSeasonState: [
        { ...base.teamSeasonState[0], is_eliminated: true, eliminated_week: null },
      ],
    };

    // Written empty.
    const [emptySnapshot] = joinBoardTeams({
      ...eliminated,
      finalRosters: [
        { team_id: 7, eliminated_week: 6, holdings: [], frozen_at: "2026-10-15T05:00:00Z" },
      ],
    });
    expect(emptySnapshot.isRosterFrozen).toBe(false);
    expect(emptySnapshot.roster.map((p) => p.sleeperPlayerId)).toEqual([
      "4046",
      "9999",
    ]);
    // The snapshot still supplies the elimination week the state row lacks.
    expect(emptySnapshot.isEliminated).toBe(true);
    expect(emptySnapshot.eliminatedWeek).toBe(6);

    // Every entry unusable, which narrows to the same nothing.
    const [malformedSnapshot] = joinBoardTeams({
      ...eliminated,
      finalRosters: [
        {
          team_id: 7,
          eliminated_week: 6,
          holdings: [null, { slot: "starter", slot_index: 0 }] as unknown as
            FinalRosterHolding[],
          frozen_at: "2026-10-15T05:00:00Z",
        },
      ],
    });
    expect(malformedSnapshot.isRosterFrozen).toBe(false);
    expect(malformedSnapshot.roster.map((p) => p.sleeperPlayerId)).toEqual([
      "4046",
      "9999",
    ]);
    expect(malformedSnapshot.eliminatedWeek).toBe(6);
  });

  // Every test above drives a one-team board. This one drives three teams through a single call
  // — one fully populated, one with no state, projection or holdings rows at all, and one
  // eliminated onto a frozen snapshot — so a row landing on the wrong card shows up here.
  it("joins three teams at once without leaking a row across cards", () => {
    const base = raw();
    const board = joinBoardTeams({
      ...base,
      teams: [
        { id: 7, member_id: 3, sleeper_roster_id: 1, team_name: "The Choppers" },
        { id: 8, member_id: 4, sleeper_roster_id: 2, team_name: "Fresh Meat" },
        { id: 9, member_id: 5, sleeper_roster_id: 3, team_name: "Headless" },
      ],
      members: [
        { id: 3, sleeper_display_name: "benray", nickname: "Ben" },
        { id: 4, sleeper_display_name: "kayla", nickname: null },
        { id: 5, sleeper_display_name: null, nickname: null },
      ],
      teamSeasonState: [
        base.teamSeasonState[0],
        {
          ...base.teamSeasonState[0],
          team_id: 9,
          faab_remaining: 12,
          wins: 0,
          losses: 3,
          points_for: 190.25,
          is_eliminated: true,
          eliminated_week: 4,
          elimination_source: "sleeper_inferred",
        },
      ],
      teamWeekProjections: [
        base.teamWeekProjections[0],
        { ...base.teamWeekProjections[0], team_id: 9, projected_points: 88.1 },
      ],
      rosterHoldings: [
        ...base.rosterHoldings,
        {
          team_id: 9,
          sleeper_player_id: "5000",
          slot: "starter",
          slot_index: 0,
          lineup_position: "WR",
        },
      ],
      players: [
        ...base.players,
        {
          sleeper_player_id: "6794",
          full_name: "Justin Jefferson",
          position: "WR",
          team: "MIN",
        },
      ],
      finalRosters: [
        {
          team_id: 9,
          eliminated_week: 4,
          holdings: [
            {
              sleeper_player_id: "6794",
              slot: "starter",
              slot_index: 0,
              lineup_position: "WR",
            },
          ],
          frozen_at: "2026-10-01T05:00:00Z",
        },
      ],
    });

    expect(board.map((t) => t.teamId)).toEqual([7, 8, 9]);
    const [populated, bare, eliminated] = board;

    expect(populated.ownerName).toBe("Ben");
    expect(populated.roster.map((p) => p.sleeperPlayerId)).toEqual(["4046", "9999"]);
    expect(populated.pointsFor).toBe(301.5);
    expect(populated.faabRemaining).toBe(75);
    expect(populated.isRosterFrozen).toBe(false);

    // No state row, no projection row, no holdings and no weekly results still gets a card.
    expect(bare.ownerName).toBe("kayla");
    expect(bare.teamName).toBe("Fresh Meat");
    expect(bare.roster).toEqual([]);
    expect(bare.pointsFor).toBe(0);
    expect(bare.faabRemaining).toBeNull();
    expect(bare.wins).toBe(0);
    expect(bare.losses).toBe(0);
    expect(bare.ties).toBe(0);
    expect(bare.projectedPoints).toBeNull();
    expect(bare.coveragePct).toBeNull();
    expect(bare.isProvisional).toBe(true);
    expect(bare.isEliminated).toBe(false);
    expect(bare.isRosterFrozen).toBe(false);

    expect(eliminated.ownerName).toBe("Unknown owner");
    expect(eliminated.isEliminated).toBe(true);
    expect(eliminated.eliminatedWeek).toBe(4);
    expect(eliminated.projectedPoints).toBe(88.1);
    expect(eliminated.isRosterFrozen).toBe(true);
    expect(eliminated.roster.map((p) => p.sleeperPlayerId)).toEqual(["6794"]);

    // No holding reached a card it does not belong to, and team 9's live holding stayed off
    // the board entirely because its snapshot won.
    expect(board.map((t) => t.roster.map((p) => p.sleeperPlayerId))).toEqual([
      ["4046", "9999"],
      [],
      ["6794"],
    ]);
    expect(
      board.flatMap((t) => t.roster.map((p) => p.sleeperPlayerId)),
    ).not.toContain("5000");
  });
});
