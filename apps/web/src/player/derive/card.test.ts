/** @vitest-environment node */
import { describe, expect, it } from "vitest";

import type { BoardTeam, RosterPlayer } from "@/board/types";

import { buildPlayerCardView, type PlayerCardInput } from "./card";

const player = (over: Partial<RosterPlayer> = {}): RosterPlayer => ({
  sleeperPlayerId: "9493",
  fullName: "Puka Nacua",
  position: "WR",
  nflTeam: "LAR",
  slot: "starter",
  slotIndex: 3,
  lineupPosition: "WR",
  projectedPoints: 14.1,
  livePoints: 7.8,
  injuryStatus: "Questionable",
  draft: {
    teamId: 11,
    amount: 53,
    pickNo: 1,
    round: 1,
    position: "WR",
    draftedAt: "2026-09-07T23:01:30.433Z",
  },
  draftedHere: true,
  ...over,
});

const team = (over: Partial<BoardTeam> & { teamId: number }): BoardTeam => ({
  teamName: `Team ${over.teamId}`,
  ownerName: `owner${over.teamId}`,
  sleeperRosterId: over.teamId,
  score: null,
  scoreSyncedAt: null,
  projectedPoints: 100,
  coveragePct: 100,
  isProvisional: false,
  projectionComputedAt: null,
  faabRemaining: 50,
  pointsFor: 100,
  startersProjected: 9,
  starterSlots: 9,
  isEliminated: false,
  eliminatedWeek: null,
  eliminationSource: null,
  emptySlots: null,
  isRosterFrozen: false,
  risk: null,
  roster: [],
  ...over,
});

const DRAFTED_AT = "2026-09-07T23:01:30.433Z";

const input = (over: Partial<PlayerCardInput> = {}): PlayerCardInput => ({
  sleeperPlayerId: "9493",
  season: 2026,
  teams: [
    team({ teamId: 11, ownerName: "Ray Regime", roster: [player()] }),
    team({ teamId: 3 }),
  ],
  draftPicks: [
    { team_id: 11, sleeper_player_id: "9493", pick_no: 1, round: 1, position: "WR", amount: 53, drafted_at: DRAFTED_AT },
    { team_id: 3, sleeper_player_id: "4046", pick_no: 2, round: 1, position: "QB", amount: 45, drafted_at: DRAFTED_AT },
    { team_id: 3, sleeper_player_id: "1111", pick_no: 3, round: 1, position: "WR", amount: 31, drafted_at: DRAFTED_AT },
  ],
  memberIdByTeamId: new Map([
    [11, 1],
    [3, 2],
  ]),
  directory: null,
  otherPlayers: [],
  transactions: [],
  moves: [],
  seasonScores: [{ week: 1, team_id: 11, players_points: { "9493": 7.8 } }],
  registered: [],
  ...over,
});

describe("buildPlayerCardView", () => {
  it("names the player from his roster row and carries his numbers", () => {
    const view = buildPlayerCardView(input());
    expect(view.name).toBe("Puka Nacua");
    expect(view.position).toBe("WR");
    expect(view.nflTeam).toBe("LAR");
    expect(view.injuryStatus).toBe("Questionable");
    expect(view.numbers).toEqual({
      rostered: true,
      projected: 14.1,
      live: 7.8,
      season: { total: 7.8, weeks: 1 },
    });
  });

  it("carries the draft with the drafter's label and the context line", () => {
    const view = buildPlayerCardView(input());
    expect(view.draft).toEqual({
      amount: 53,
      pickNo: 1,
      ownerName: "Ray Regime",
      contextLine: "1st priciest pick · 1st WR · WR average $42",
      stillHere: true,
    });
  });

  it("reads an undrafted player as such", () => {
    const view = buildPlayerCardView(input({ draftPicks: [] }));
    expect(view.draft).toBeNull();
  });

  it("falls back to the directory for a player nobody rosters, and says so", () => {
    const view = buildPlayerCardView(
      input({
        teams: [team({ teamId: 11, ownerName: "Ray Regime" })],
        directory: {
          sleeper_player_id: "9493",
          full_name: "Puka Nacua",
          position: "WR",
          team: "LAR",
          injury_status: null,
        },
      }),
    );
    expect(view.name).toBe("Puka Nacua");
    expect(view.numbers).toEqual({
      rostered: false,
      season: { total: 7.8, weeks: 1 },
    });
    expect(view.draft?.stillHere).toBe(false);
  });

  it("labels every team the journey names, and every other player it names", () => {
    const view = buildPlayerCardView(
      input({
        otherPlayers: [
          {
            sleeper_player_id: "12534",
            full_name: "Brock Bowers",
            position: "TE",
            team: "LV",
            injury_status: null,
          },
        ],
      }),
    );
    expect(view.ownerLabelByTeamId.get(11)).toBe("Ray Regime");
    expect(view.playerNameById.get("12534")).toBe("Brock Bowers");
  });

  it("names an unknown player and an unknown team honestly", () => {
    const view = buildPlayerCardView(input({ teams: [], directory: null }));
    expect(view.name).toBe("Unknown player 9493");
    expect(view.ownerLabelByTeamId.get(99)).toBeUndefined();
  });
});
