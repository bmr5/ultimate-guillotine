/**
 * The position view is filters, a median and comparators over plain numbers, so it runs under
 * node like the other derive modules.
 *
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { BoardTeam, RosterPlayer } from "../types";
import { positionView, slotAcceptsPosition } from "./position";

/** The league's own lineup, as `seasons.roster_positions` spells it. */
const LEAGUE_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"];

const player = (
  over: Partial<RosterPlayer> & { sleeperPlayerId: string },
): RosterPlayer => ({
  fullName: `Player ${over.sleeperPlayerId}`,
  position: "TE",
  nflTeam: "KC",
  slot: "bench",
  slotIndex: null,
  lineupPosition: null,
  projectedPoints: null,
  injuryStatus: null,
  ...over,
});

/** A starting tight end; `slotIndex` defaults to the TE slot of `LEAGUE_SLOTS`. */
const te = (
  sleeperPlayerId: string,
  projectedPoints: number | null,
  slotIndex = 5,
): RosterPlayer =>
  player({
    sleeperPlayerId,
    slot: "starter",
    slotIndex,
    lineupPosition: "TE",
    position: "TE",
    projectedPoints,
  });

const team = (over: Partial<BoardTeam> & { teamId: number }): BoardTeam => ({
  teamName: `Team ${over.teamId}`,
  ownerName: `owner${over.teamId}`,
  sleeperRosterId: over.teamId,
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
  roster: [],
  ...over,
});

interface SlotCase {
  slot: string;
  position: "QB" | "RB" | "WR" | "TE" | "K" | "DEF";
  accepts: boolean;
}

const SLOT_CASES: SlotCase[] = [
  { slot: "TE", position: "TE", accepts: true },
  { slot: "TE", position: "WR", accepts: false },
  // Ben's own case: an empty FLEX is a hole a tight end could fill.
  { slot: "FLEX", position: "TE", accepts: true },
  { slot: "FLEX", position: "RB", accepts: true },
  { slot: "FLEX", position: "WR", accepts: true },
  { slot: "FLEX", position: "QB", accepts: false },
  { slot: "FLEX", position: "K", accepts: false },
  { slot: "SUPER_FLEX", position: "QB", accepts: true },
  { slot: "WRRB_FLEX", position: "TE", accepts: false },
  { slot: "WRRB_FLEX", position: "RB", accepts: true },
  { slot: "REC_FLEX", position: "WR", accepts: true },
  { slot: "DEF", position: "DEF", accepts: true },
];

describe("slotAcceptsPosition", () => {
  it.each(SLOT_CASES)(
    "a $slot slot accepts $position: $accepts",
    ({ slot, position, accepts }) => {
      expect(slotAcceptsPosition(slot, position)).toBe(accepts);
    },
  );
});

describe("positionView", () => {
  it("gives every team a row, players at the position only", () => {
    const rows = positionView(
      [
        team({
          teamId: 1,
          roster: [
            te("kelce", 14.1),
            player({
              sleeperPlayerId: "laporta",
              position: "TE",
              projectedPoints: 9.2,
            }),
            player({
              sleeperPlayerId: "wr",
              position: "WR",
              projectedPoints: 30,
            }),
          ],
        }),
        team({ teamId: 2, roster: [] }),
      ],
      "TE",
      LEAGUE_SLOTS,
    );
    expect(rows).toHaveLength(2);
    expect(rows[0].players.map((p) => p.sleeperPlayerId)).toEqual([
      "kelce",
      "laporta",
    ]);
    // The starter leads and is marked; the bench tight end follows.
    expect(rows[0].players.map((p) => p.isStarter)).toEqual([true, false]);
    expect(rows[0].players[0].projectedPoints).toBe(14.1);
    expect(rows[1].players).toEqual([]);
  });

  it("counts an empty FLEX as a hole for RB, WR and TE but not for QB", () => {
    // Only the TE slot is filled, so the empty FLEX is the second hole a tight end could fill
    // — except it is the only one, the TE slot being taken — and the third for a running back.
    const holed = team({ teamId: 1, roster: [te("kelce", 14.1)] });
    expect(positionView([holed], "TE", LEAGUE_SLOTS)[0].emptySlots).toBe(1);
    expect(positionView([holed], "RB", LEAGUE_SLOTS)[0].emptySlots).toBe(3);
    expect(positionView([holed], "QB", LEAGUE_SLOTS)[0].emptySlots).toBe(1);
    expect(positionView([holed], "K", LEAGUE_SLOTS)[0].emptySlots).toBe(1);
  });

  it("counts no holes at all when the league's lineup is not known", () => {
    const rows = positionView(
      [team({ teamId: 1, roster: [te("kelce", 14.1)] })],
      "TE",
      [],
    );
    expect(rows[0].emptySlots).toBe(0);
    expect(rows[0].likelyBidder).toBe(false);
  });

  it("flags a team with an empty slot at the position as a likely bidder", () => {
    const rows = positionView(
      [
        team({ teamId: 1, roster: [te("kelce", 20, 0)] }),
        team({ teamId: 2, roster: [] }),
      ],
      "TE",
      ["TE"],
    );
    expect(rows.map((r) => [r.teamId, r.likelyBidder])).toEqual([
      [1, false],
      [2, true],
    ]);
    expect(rows[1].emptySlots).toBe(1);
  });

  it("flags a team whose starter at the position is out, and says so", () => {
    // Ben's addendum: "my TE just got injured and I need to figure out who would bid on his
    // replacement." A team holding a tight end who is not playing needs one as surely as a
    // team holding none, and the reason is the useful half of the answer.
    const rows = positionView(
      [
        team({ teamId: 1, roster: [te("kelce", 20, 0)] }),
        team({
          teamId: 2,
          roster: [
            player({
              sleeperPlayerId: "hurt",
              slot: "starter",
              slotIndex: 0,
              lineupPosition: "TE",
              position: "TE",
              projectedPoints: null,
              injuryStatus: "Out",
            }),
          ],
        }),
      ],
      "TE",
      ["TE"],
    );
    expect(rows.map((r) => [r.teamId, r.likelyBidder])).toEqual([
      [1, false],
      [2, true],
    ]);
    expect(rows[1].likelyBidderReason).toBe("starter out");
    expect(rows[0].likelyBidderReason).toBeNull();
    // The slot is filled, so this is not the empty-slot rule firing under another name.
    expect(rows[1].emptySlots).toBe(0);
    expect(rows[1].players[0].injuryStatus).toBe("Out");
  });

  it("leaves a questionable starter unflagged: a doubt is not an absence", () => {
    const rows = positionView(
      [
        team({ teamId: 1, roster: [te("kelce", 20, 0)] }),
        team({
          teamId: 2,
          roster: [
            player({
              sleeperPlayerId: "maybe",
              slot: "starter",
              slotIndex: 0,
              lineupPosition: "TE",
              position: "TE",
              // The same projection as the other team's starter, so the median rule cannot
              // fire and the only thing under test is the status.
              projectedPoints: 20,
              injuryStatus: "Questionable",
            }),
          ],
        }),
      ],
      "TE",
      ["TE"],
    );
    expect(rows.find((r) => r.teamId === 2)?.likelyBidderReason).toBeNull();
  });

  it("names the empty slot and the thin starter as their own reasons", () => {
    const rows = positionView(
      [
        team({ teamId: 1, roster: [te("best", 20, 0)] }),
        team({ teamId: 2, roster: [te("mid", 10, 0)] }),
        team({ teamId: 3, roster: [te("worst", 4, 0)] }),
        team({ teamId: 4, roster: [] }),
      ],
      "TE",
      ["TE"],
    );
    const reason = (teamId: number) =>
      rows.find((r) => r.teamId === teamId)?.likelyBidderReason;
    expect(reason(1)).toBeNull();
    expect(reason(3)).toBe("below median");
    expect(reason(4)).toBe("empty slot");
  });

  it("flags a team whose best starter is below the league median", () => {
    // Bests are 20, 10 and 4, so the median is 10 and only the 4 is below it.
    const rows = positionView(
      [
        team({ teamId: 1, faabRemaining: 30, roster: [te("best", 20, 0)] }),
        team({ teamId: 2, faabRemaining: 20, roster: [te("mid", 10, 0)] }),
        team({ teamId: 3, faabRemaining: 10, roster: [te("worst", 4, 0)] }),
      ],
      "TE",
      ["TE"],
    );
    expect(rows.map((r) => [r.teamId, r.likelyBidder])).toEqual([
      [1, false],
      [2, false],
      [3, true],
    ]);
  });

  it("takes the median from the visible teams, not from the whole league", () => {
    // The same 4-point tight end is the median of a two-team view and below it in a four-team
    // one: the flag answers "who bids in what I am looking at".
    const worst = team({
      teamId: 3,
      faabRemaining: 10,
      roster: [te("w", 4, 0)],
    });
    const narrow = positionView(
      [team({ teamId: 1, roster: [te("b", 2, 0)] }), worst],
      "TE",
      ["TE"],
    );
    expect(narrow.find((r) => r.teamId === 3)?.likelyBidder).toBe(false);
  });

  it("orders by FAAB descending, ties by projection, eliminated last", () => {
    const rows = positionView(
      [
        team({ teamId: 1, faabRemaining: 10, projectedPoints: 200 }),
        team({ teamId: 2, faabRemaining: 90, projectedPoints: 10 }),
        team({ teamId: 3, faabRemaining: 90, projectedPoints: 150 }),
        team({
          teamId: 4,
          faabRemaining: 900,
          projectedPoints: 300,
          isEliminated: true,
        }),
      ],
      "TE",
      [],
    );
    expect(rows.map((r) => r.teamId)).toEqual([3, 2, 1, 4]);
  });

  it("sorts by projection when the view asks for it, tie-broken by FAAB", () => {
    const rows = positionView(
      [
        team({ teamId: 1, faabRemaining: 10, projectedPoints: 200 }),
        team({ teamId: 2, faabRemaining: 90, projectedPoints: 10 }),
        team({ teamId: 3, faabRemaining: 5, projectedPoints: 200 }),
      ],
      "TE",
      [],
      "projection",
    );
    expect(rows.map((r) => r.teamId)).toEqual([1, 3, 2]);
  });

  it("sorts a team with no FAAB row after every team that has one", () => {
    const rows = positionView(
      [
        team({ teamId: 1, faabRemaining: null }),
        team({ teamId: 2, faabRemaining: 0 }),
      ],
      "TE",
      [],
    );
    expect(rows.map((r) => r.teamId)).toEqual([2, 1]);
  });

  it("carries the owner label, FAAB and the team itself onto the row", () => {
    const source = team({ teamId: 1, ownerName: "Nick R", faabRemaining: 715 });
    const [row] = positionView([source], "TE", []);
    expect(row.ownerName).toBe("Nick R");
    expect(row.faabRemaining).toBe(715);
    // The whole team rides along so the row can expand into the usual roster panel.
    expect(row.team).toBe(source);
  });

  it("reads a defence by its Sleeper position code", () => {
    const rows = positionView(
      [
        team({
          teamId: 1,
          roster: [
            player({
              sleeperPlayerId: "SEA",
              position: "DEF",
              projectedPoints: 7,
            }),
          ],
        }),
      ],
      "DEF",
      [],
    );
    expect(rows[0].players.map((p) => p.sleeperPlayerId)).toEqual(["SEA"]);
  });

  it("ignores a player the directory has no position for", () => {
    const rows = positionView(
      [
        team({
          teamId: 1,
          roster: [player({ sleeperPlayerId: "unknown", position: null })],
        }),
      ],
      "TE",
      [],
    );
    expect(rows[0].players).toEqual([]);
  });

  it("does not mutate the teams it was handed", () => {
    const teams = [
      team({ teamId: 2, faabRemaining: 1 }),
      team({ teamId: 1, faabRemaining: 99 }),
    ];
    positionView(teams, "TE", LEAGUE_SLOTS);
    expect(teams.map((t) => t.teamId)).toEqual([2, 1]);
  });
});
