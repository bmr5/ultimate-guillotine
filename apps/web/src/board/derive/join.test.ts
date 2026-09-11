/**
 * The join is Map lookups over plain rows: no DOM, no timers.
 *
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { FinalRosterHolding, TableRow } from "../types";
import { joinBoardTeams, resolveOwnerLabel, type BoardRawData } from "./join";

const raw = (over: Partial<BoardRawData> = {}): BoardRawData => ({
  teams: [
    { id: 7, member_id: 3, sleeper_roster_id: 1, team_name: "The Choppers" },
  ],
  members: [{ id: 3, sleeper_display_name: "benray", nickname: "Ben" }],
  // Empty by default: the shape before the first score sync of a week has landed, in which
  // every card reads `0.0` and no roster row carries a live figure.
  teamWeekScores: [],
  teamSeasonState: [
    {
      season_id: 1,
      team_id: 7,
      faab_budget: 100,
      faab_used: 25,
      faab_remaining: 75,
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
    {
      sleeper_player_id: "4046",
      full_name: "Patrick Mahomes",
      position: "QB",
      team: "KC",
      injury_status: null,
    },
  ],
  playerProjections: [{ sleeper_player_id: "4046", league_points: 22.6 }],
  weeklyResults: [
    { week: 1, team_id: 7, points: 150.75, is_final: true, state_version: 1 },
    { week: 2, team_id: 7, points: 150.75, is_final: true, state_version: 1 },
  ],
  finalRosters: [],
  draftPicks: [],
  survivalSnapshot: null,
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
    expect(
      resolveOwnerLabel({ nickname: null, sleeper_display_name: null }),
    ).toBe("Unknown owner");
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
    expect(team.pointsFor).toBe(301.5);
    // The two figures the partial badge's tooltip is written from.
    expect(team.startersProjected).toBe(9);
    expect(team.starterSlots).toBe(9);
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

  it("carries the directory's injury status onto the roster row", () => {
    const [team] = joinBoardTeams(raw());
    expect(team.roster[0].injuryStatus).toBeNull();

    const injured = raw();
    injured.players = injured.players.map((player) =>
      player.sleeper_player_id === "4046"
        ? { ...player, injury_status: "Out" }
        : player,
    );
    const [withInjury] = joinBoardTeams(injured);
    expect(withInjury.roster[0].injuryStatus).toBe("Out");
  });

  it("reads a holding with no directory row as available, not injured", () => {
    // `roster_holdings` has no FK to `players` on purpose, so an id the filtered directory
    // drops still gets a row. Nothing is known about it — including whether he is hurt.
    const [team] = joinBoardTeams(raw());
    const unknown = team.roster.find((p) => p.sleeperPlayerId === "9999");
    expect(unknown?.fullName).toBe("Unknown player 9999");
    expect(unknown?.injuryStatus).toBeNull();
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
      raw({
        members: [{ id: 3, sleeper_display_name: "benray", nickname: null }],
      }),
    );
    expect(team.ownerName).toBe("benray");
  });

  it("falls back to weekly_results for the total when there is no state row", () => {
    const [team] = joinBoardTeams(raw({ teamSeasonState: [] }));
    expect(team.pointsFor).toBe(301.5);
    expect(team.faabRemaining).toBeNull();
    expect(team.isEliminated).toBe(false);
  });

  it("treats a team with no projection row as provisional with no number", () => {
    const [team] = joinBoardTeams(raw({ teamWeekProjections: [] }));
    expect(team.projectedPoints).toBeNull();
    expect(team.coveragePct).toBeNull();
    expect(team.isProvisional).toBe(true);
    // Null rather than zero: nobody counted the starters, which is not the same statement as
    // "none of them are projected", and the badge's tooltip has nothing to say either way.
    expect(team.startersProjected).toBeNull();
    expect(team.starterSlots).toBeNull();
  });

  it("carries the week's starter counts onto the team", () => {
    const base = raw();
    const [team] = joinBoardTeams({
      ...base,
      teamWeekProjections: [
        {
          ...base.teamWeekProjections[0],
          starters_projected: 6,
          starter_slots: 9,
          coverage_pct: 66.67,
        },
      ],
    });
    expect(team.startersProjected).toBe(6);
    expect(team.starterSlots).toBe(9);
    expect(team.coveragePct).toBe(66.67);
  });

  it("carries the week's empty_slots count onto the team", () => {
    const base = raw();
    const [team] = joinBoardTeams({
      ...base,
      teamWeekProjections: [{ ...base.teamWeekProjections[0], empty_slots: 2 }],
    });
    expect(team.emptySlots).toBe(2);
  });

  it("leaves the empty-slot count null when the week has no projection row", () => {
    // null, never zero: "nobody counted" is a different statement from "the lineup is full",
    // and the card counts the holes off the roster itself in that case.
    const [team] = joinBoardTeams(raw({ teamWeekProjections: [] }));
    expect(team.emptySlots).toBeNull();
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
        {
          ...base.teamSeasonState[0],
          is_eliminated: true,
          eliminated_week: null,
        },
      ],
      finalRosters: [
        {
          team_id: 7,
          eliminated_week: 6,
          holdings: [],
          frozen_at: "2026-10-15T05:00:00Z",
        },
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
          {
            team_id: 7,
            eliminated_week: 4,
            holdings: [],
            frozen_at: "2026-10-01T05:00:00Z",
          },
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
        {
          ...base.teamSeasonState[0],
          is_eliminated: true,
          eliminated_week: null,
        },
      ],
    };

    // Written empty.
    const [emptySnapshot] = joinBoardTeams({
      ...eliminated,
      finalRosters: [
        {
          team_id: 7,
          eliminated_week: 6,
          holdings: [],
          frozen_at: "2026-10-15T05:00:00Z",
        },
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
          holdings: [
            null,
            { slot: "starter", slot_index: 0 },
          ] as unknown as FinalRosterHolding[],
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
        {
          id: 7,
          member_id: 3,
          sleeper_roster_id: 1,
          team_name: "The Choppers",
        },
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
          injury_status: "Out",
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
    expect(populated.roster.map((p) => p.sleeperPlayerId)).toEqual([
      "4046",
      "9999",
    ]);
    expect(populated.pointsFor).toBe(301.5);
    expect(populated.faabRemaining).toBe(75);
    expect(populated.isRosterFrozen).toBe(false);

    // No state row, no projection row, no holdings and no weekly results still gets a card.
    expect(bare.ownerName).toBe("kayla");
    expect(bare.teamName).toBe("Fresh Meat");
    expect(bare.roster).toEqual([]);
    expect(bare.pointsFor).toBe(0);
    expect(bare.faabRemaining).toBeNull();
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

/**
 * Ben's ruling: the card shows the current score beside the projection. The join is where a
 * `team_week_scores` row becomes a card's `score` and a roster row's `livePoints`.
 */
describe("joinBoardTeams live scores", () => {
  const scoreRow = (over: Partial<TableRow<"team_week_scores">> = {}) => ({
    season_id: 1,
    team_id: 7,
    week: 3,
    points: 84.24,
    players_points: { "4046": 12.4, "9999": 3.5 },
    starters: ["4046"],
    synced_at: "2026-09-13T17:30:00Z",
    ...over,
  });

  it("puts the week's points and stamp on the team", () => {
    const [board] = joinBoardTeams(raw({ teamWeekScores: [scoreRow()] }));
    expect(board.score).toBe(84.24);
    expect(board.scoreSyncedAt).toBe("2026-09-13T17:30:00Z");
  });

  it("adds a schedule-adjusted projection without changing the original or actual", () => {
    const rows = raw({ teamWeekScores: [scoreRow({ points: 12.4 })] });
    const [live] = joinBoardTeams({ ...rows, weekSchedule: { KC: "live" } });
    expect(live.currentProjectedPoints).toBe(22.6);
    const [finished] = joinBoardTeams({
      ...rows,
      weekSchedule: { KC: "done" },
    });
    expect(finished.currentProjectedPoints).toBe(12.4);
    expect(finished.projectedPoints).toBe(112.4);
    expect(finished.score).toBe(12.4);
    expect(joinBoardTeams(rows)[0].currentProjectedPoints).toBeNull();
  });

  it("leaves both null when the week has no score row", () => {
    // Null is "no row", which the card renders as `0.0`. The distinction still matters to the
    // header, which shows the scores stamp only when a row exists.
    const [board] = joinBoardTeams(raw({ teamWeekScores: [] }));
    expect(board.score).toBeNull();
    expect(board.scoreSyncedAt).toBeNull();
  });

  it("hangs each player's live points off his roster row, bench included", () => {
    const [board] = joinBoardTeams(raw({ teamWeekScores: [scoreRow()] }));
    const byId = new Map(board.roster.map((p) => [p.sleeperPlayerId, p]));
    expect(byId.get("4046")?.livePoints).toBe(12.4);
    // The map covers the whole roster; only the panel decides which rows show the number.
    expect(byId.get("9999")?.livePoints).toBe(3.5);
  });

  it("leaves a player the points map does not name at null, never at zero", () => {
    const [board] = joinBoardTeams(
      raw({ teamWeekScores: [scoreRow({ players_points: { "4046": 12.4 } })] }),
    );
    const byId = new Map(board.roster.map((p) => [p.sleeperPlayerId, p]));
    expect(byId.get("9999")?.livePoints).toBeNull();
  });

  it("narrows a stored points map rather than trusting its declared type", () => {
    // jsonb: the sync writes numbers and the typed `Database` says so, but a stored row is
    // data some earlier build wrote. A NaN would otherwise reach a roster row as the text
    // `NaN`, since that is what `toFixed` renders it as.
    const [board] = joinBoardTeams(
      raw({
        teamWeekScores: [
          scoreRow({
            players_points: {
              "4046": Number.NaN,
              "9999": 3.5,
            } as Record<string, number>,
          }),
        ],
      }),
    );
    const byId = new Map(board.roster.map((p) => [p.sleeperPlayerId, p]));
    expect(byId.get("4046")?.livePoints).toBeNull();
    expect(byId.get("9999")?.livePoints).toBe(3.5);
  });

  it("keeps one team's live points off another team's roster", () => {
    const [board] = joinBoardTeams(
      raw({
        teamWeekScores: [
          scoreRow({ team_id: 8, players_points: { "4046": 99.9 } }),
        ],
      }),
    );
    // Team 7 has no row of its own, so its starter has no live figure — team 8's map is not
    // a league-wide lookup, and reading it that way would put another roster's points here.
    expect(board.score).toBeNull();
    expect(board.roster.every((p) => p.livePoints === null)).toBe(true);
  });
});

describe("the drafted-here rule", () => {
  const picks = [
    {
      team_id: 7,
      sleeper_player_id: "4046",
      pick_no: 1,
      round: 1,
      position: "QB",
      amount: 45,
      drafted_at: "2026-09-07T23:01:30.433Z",
    },
    {
      team_id: 8,
      sleeper_player_id: "9999",
      pick_no: 2,
      round: 1,
      position: "RB",
      amount: 12,
      drafted_at: "2026-09-07T23:01:30.433Z",
    },
  ];

  it("marks a player still on the team that drafted him, and carries the pick", () => {
    const [team] = joinBoardTeams(raw({ draftPicks: picks }));
    const mahomes = team.roster.find((p) => p.sleeperPlayerId === "4046");
    expect(mahomes?.draftedHere).toBe(true);
    expect(mahomes?.draft).toEqual({
      teamId: 7,
      amount: 45,
      pickNo: 1,
      round: 1,
      position: "QB",
      draftedAt: "2026-09-07T23:01:30.433Z",
    });
  });

  it("does not mark a player another team drafted, but still carries his pick", () => {
    const [team] = joinBoardTeams(raw({ draftPicks: picks }));
    const acquired = team.roster.find((p) => p.sleeperPlayerId === "9999");
    expect(acquired?.draftedHere).toBe(false);
    expect(acquired?.draft?.teamId).toBe(8);
  });

  it("leaves an undrafted pickup with no pick and no mark", () => {
    const [team] = joinBoardTeams(raw());
    for (const player of team.roster) {
      expect(player.draft).toBeNull();
      expect(player.draftedHere).toBe(false);
    }
  });

  it("applies the same rule to a frozen roster", () => {
    const frozen: FinalRosterHolding[] = [
      {
        sleeper_player_id: "4046",
        slot: "starter",
        slot_index: 0,
        lineup_position: "QB",
      },
    ];
    const [team] = joinBoardTeams(
      raw({
        draftPicks: picks,
        teamSeasonState: [
          {
            ...raw().teamSeasonState[0],
            is_eliminated: true,
            eliminated_week: 2,
          },
        ],
        finalRosters: [
          {
            team_id: 7,
            eliminated_week: 2,
            holdings: frozen,
            frozen_at: "2026-09-20T00:00:00Z",
          },
        ],
      }),
    );
    expect(team.isRosterFrozen).toBe(true);
    expect(team.roster[0]?.draftedHere).toBe(true);
  });
});

/**
 * The Daily's odds ride on the card from the week's newest `survival_snapshots` row. Keyed by
 * team id like everything else here; a team the Daily did not rate — it rates the live teams
 * only — simply has none.
 */
describe("joinBoardTeams with the week's odds", () => {
  const SNAPSHOT_AT = "2026-09-10T15:15:23Z";
  const odds = (team_id: number, probability: number) => ({
    team_id,
    label: `Team ${team_id}`,
    points: 7.8,
    projected_final: 88.2,
    pending: 8,
    adverse_event: "gulag_entry",
    probability,
    is_estimated: false,
  });

  it("hangs a team's odds off its card", () => {
    const [team] = joinBoardTeams(
      raw({
        survivalSnapshot: {
          snapshot_at: SNAPSHOT_AT,
          results: [odds(7, 0.37)],
        },
      }),
    );
    expect(team.risk).toEqual({
      probability: 0.37,
      adverseEvent: "gulag_entry",
      isEstimated: false,
      settled: false,
      snapshotAt: SNAPSHOT_AT,
    });
  });

  it("gives a team the Daily did not rate no odds", () => {
    const [team] = joinBoardTeams(
      raw({
        survivalSnapshot: {
          snapshot_at: SNAPSHOT_AT,
          results: [odds(8, 0.37)],
        },
      }),
    );
    expect(team.risk).toBeNull();
  });

  it("gives every team no odds before the week's first Daily", () => {
    const [team] = joinBoardTeams(raw({ survivalSnapshot: null }));
    expect(team.risk).toBeNull();
  });
});
