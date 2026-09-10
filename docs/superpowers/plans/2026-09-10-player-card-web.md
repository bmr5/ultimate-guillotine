# Player Card Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the board, mark every player still on the team that drafted him, and open a card from any player's name showing his draft price and drafter, where that price sat in the auction, his numbers, and his season journey with the league's own announcements matched in.

**Architecture:** The board's join gains the draft pick per player and the one-line drafted-here rule. A shared `PlayerName` renders the name as a button plus the mark, in both places a roster row is drawn. One controlled dialog mounts at the page level, keyed by `?player=<id>` in the URL, and reads a `PlayerCardView` built by pure derivations from three lazy queries (the player's transactions, the season's weekly scores, the trades page's registered trades) plus what the board already holds.

**Tech Stack:** React 19, react-router v8, TanStack Query v5, postgrest-js, Tailwind v4 + shadcn primitives, lucide-react, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-10-player-card-design.md` — sections "The Mark", "The Card", "Privacy and Safety", and the web half of "Test and Rollout". The data-layer half is `2026-09-10-player-card-data.md` and is done: `public.draft_picks`, `public.transactions`, `public.transaction_moves` exist and are populated.

## Global Constraints

- Every command runs from the repository root. `pnpm test:web` runs the web suite, `pnpm lint` the web lint, and `pnpm --filter @ultimate-guillotine/web exec tsc --noEmit` the typecheck. All three must pass before a commit.
- Tests are colocated `*.test.ts(x)`; pure derive modules carry `@vitest-environment node`; component tests use Testing Library with `fireEvent`, roles and visible text, and `data-*` handles for state; `globals: false`, so import from `vitest`.
- Season-scoped by construction: every new query filters on the board's `seasonId`; registered trades are filtered to the board's `season` year. The card never mixes seasons.
- Owner labels are `resolveOwnerLabel`'s: nickname, else Sleeper display name, never the username. A party the directory cannot name reads as `FORMER_MANAGER`.
- The mark is a muted 12px lucide `Anchor` rendered by `ExplainedBadge` with description `Drafted by <owner> for $<amount>`. A control never nests inside another control.
- Trade match rule: same season, the set of member ids behind the Sleeper trade's `team_ids` equals the registered trade's resolved party member ids, announcement within 72 hours of `occurred_at`, nearest wins, each registered trade links at most once, a registered trade with an unresolved party never matches.
- Competition ranks for the auction context (tied prices share the higher rank, the next rank is skipped); the position average is rounded to the dollar.
- Season points: the sum over every week's `team_week_scores` row whose `players_points` names the player, one row per week, captioned by the count of such weeks.
- Only public Sleeper data plus the registered-trade fields `/trades` already renders reach the card.
- TDD; commit on `main` after each task with all three gates green.

---

## File Structure

**Create**

| Path | Responsibility |
| --- | --- |
| `apps/web/src/board/derive/draft.ts` (+ `.test.ts`) | Index picks by player; the drafted-here rule; competition ranks and the context line; `ordinal`. |
| `apps/web/src/board/components/DraftedMark.tsx` | The anchor glyph as an explained badge. |
| `apps/web/src/board/components/PlayerName.tsx` (+ `.test.tsx`) | The name button plus the mark, shared by both roster rows. |
| `apps/web/src/player/fetchers.ts` | The card's three lazy reads. |
| `apps/web/src/player/queryKeys.ts` | Their keys. |
| `apps/web/src/player/derive/points.ts` (+ `.test.ts`) | Season points over rostered weeks. |
| `apps/web/src/player/derive/dateLine.ts` (+ `.test.ts`) | `Sep 9 · Wk 1`. |
| `apps/web/src/player/derive/journey.ts` (+ `.test.ts`) | Transactions and registered trades into ordered entries; the match rule. |
| `apps/web/src/player/derive/card.ts` (+ `.test.ts`) | Everything the card renders, as one `PlayerCardView`. |
| `apps/web/src/player/usePlayerCard.ts` | The three queries plus the directory and the trades hook. |
| `apps/web/src/player/components/PlayerCard.tsx` (+ `.test.tsx`) | The controlled dialog and its sections. |
| `apps/web/src/draft/derive/rows.ts` (+ `.test.ts`) | Picks joined to names and owners; the three sorts; per-team spend and the FAAB conversion; the summary. |
| `apps/web/src/draft/useDraftPage.ts` | The page's reads: season, teams, members, picks, names. |
| `apps/web/src/draft/components/DraftSkeleton.tsx` | The page's loading state. |
| `apps/web/src/app/draft/DraftPage.tsx` (+ `.test.tsx`) | The `/draft` page: summary strip, sort control, the list. |

**Modify**

| Path | Change |
| --- | --- |
| `apps/web/src/board/types.ts` | Three tables; `DraftPickInfo`; `RosterPlayer.draft` / `.draftedHere`. |
| `apps/web/src/board/fetchers.ts` | `DraftPickRow`, `fetchDraftPicks`. |
| `apps/web/src/board/queryKeys.ts` | `draftPicks`. |
| `apps/web/src/board/derive/join.ts` (+ `.test.ts`) | `BoardRawData.draftPicks`; the two new fields per roster row. |
| `apps/web/src/board/derive/position.ts` | `PositionPlayer.draft` / `.draftedHere`. |
| `apps/web/src/board/useBoardData.ts` | Load the picks; expose `draftPicks` and `memberIdByTeamId`. |
| `apps/web/src/board/components/RosterPanel.tsx` | `PlayerName` in `PlayerRow`; `ownerName` and `onOpenPlayer` props. |
| `apps/web/src/board/components/TeamCard.tsx` | Thread the two props. |
| `apps/web/src/board/components/PositionView.tsx` | `PlayerName` in the inline row; thread the props. |
| `apps/web/src/app/board/BoardPage.tsx` (+ `.test.tsx`) | `?player=`; open and close; mount the card. |
| `apps/web/src/board/components/TeamCard.test.tsx`, `PositionView.test.tsx`, `app/board/BoardPage.test.tsx` | Fixture builders gain the two roster fields and the new result fields; render helpers pass the new props. |
| `apps/web/src/router.tsx`, `apps/web/src/app/lazyPages.ts`, `apps/web/src/app/layout.tsx` | The `/draft` route, its chunk, its tab, its fallback. |
| `docs/superpowers/specs/2026-09-10-player-card-design.md` | Record the implementation decisions (see Task 9). |

---

### Task 1: Types, fetchers, keys

**Files:**
- Modify: `apps/web/src/board/types.ts`
- Modify: `apps/web/src/board/fetchers.ts`
- Modify: `apps/web/src/board/queryKeys.ts`
- Create: `apps/web/src/player/fetchers.ts`
- Create: `apps/web/src/player/queryKeys.ts`

**Interfaces:**
- Produces: `TransactionKind`, `MoveAction`, `FaabMoveEntry`, `DraftPickInfo`; `RosterPlayer.draft: DraftPickInfo | null`, `RosterPlayer.draftedHere: boolean`; `DraftPickRow`, `fetchDraftPicks(client, seasonId)`; `boardKeys.draftPicks(seasonId)`; `TransactionRow`, `TransactionMoveRow`, `SeasonScoreRow`, `fetchPlayerTransactions(client, seasonId, sleeperPlayerId) -> Promise<{ transactions, moves }>`, `fetchSeasonScores(client, seasonId)`; `playerKeys`.

- [ ] **Step 1: Extend the typed database and the roster row**

In `apps/web/src/board/types.ts`, after `EliminationSource`:

```ts
export type TransactionKind = "trade" | "waiver" | "free_agent" | "commissioner";
export type MoveAction = "add" | "drop";

/** One entry of `public.transactions.faab_moves`, as the sync writes it. */
export interface FaabMoveEntry {
  amount: number;
  from_team_id: number;
  to_team_id: number;
}

/**
 * The auction pick that brought a player into the league this season, already resolved to a
 * team id. Defined here rather than in `derive/draft` because `RosterPlayer` carries one.
 */
export interface DraftPickInfo {
  teamId: number;
  amount: number;
  pickNo: number;
  round: number;
  /** The position Sleeper recorded on the pick, which is what the auction ranked by. */
  position: string | null;
  /** The draft's start time, ISO-8601 — the same on every pick. */
  draftedAt: string;
}
```

Inside `Database.public.Tables`, after `trade_revisions`:

```ts
      /** The auction, one row per pick, keyed by season and player. Spec: player card. */
      draft_picks: ReadOnlyTable<{
        id: number;
        season_id: number;
        team_id: number;
        sleeper_player_id: string;
        sleeper_draft_id: string;
        pick_no: number;
        round: number;
        draft_slot: number;
        position: string | null;
        amount: number;
        drafted_at: string;
        synced_at: string;
      }>;
      /** One completed Sleeper transaction. `raw` is never selected by the web app. */
      transactions: ReadOnlyTable<{
        id: number;
        season_id: number;
        sleeper_transaction_id: string;
        kind: TransactionKind;
        week: number;
        occurred_at: string;
        team_ids: number[];
        faab_moves: FaabMoveEntry[];
        waiver_bid: number | null;
        raw: Json;
        synced_at: string;
      }>;
      /** One player on one side of a transaction: the per-player index the card reads. */
      transaction_moves: ReadOnlyTable<{
        id: number;
        transaction_id: number;
        season_id: number;
        sleeper_player_id: string;
        team_id: number;
        action: MoveAction;
      }>;
```

In `RosterPlayer`, after `injuryStatus`:

```ts
  /** The auction pick that brought him in this season, or null for an undrafted pickup. */
  draft: DraftPickInfo | null;
  /**
   * True when `draft` belongs to the team whose row this is — he is still on the team that
   * drafted him. The one-line rule behind the mark, computed in the join so both roster rows
   * read the same answer.
   */
  draftedHere: boolean;
```

- [ ] **Step 2: The board's draft-picks fetcher and key**

In `apps/web/src/board/fetchers.ts`, after `FinalRosterRow`:

```ts
export type DraftPickRow = Pick<
  TableRow<"draft_picks">,
  | "team_id"
  | "sleeper_player_id"
  | "pick_no"
  | "round"
  | "position"
  | "amount"
  | "drafted_at"
>;
```

At the end of the file:

```ts
/**
 * The season's auction, whole: 162 rows once a year, so it loads with the board rather than
 * per card, and the mark on every roster row derives from it without a second request.
 */
export function fetchDraftPicks(
  client: BoardClient,
  seasonId: number,
): Promise<DraftPickRow[]> {
  return unwrap<DraftPickRow>(
    client
      .from("draft_picks")
      .select(
        "team_id, sleeper_player_id, pick_no, round, position, amount, drafted_at",
      )
      .eq("season_id", seasonId),
    "draft_picks",
  );
}
```

In `apps/web/src/board/queryKeys.ts`, after `finalRosters`:

```ts
  draftPicks: (seasonId: number) => ["board", "draft_picks", seasonId] as const,
```

- [ ] **Step 3: The card's fetchers and keys**

`apps/web/src/player/fetchers.ts`:

```ts
import type { BoardClient } from "@/board/fetchers";
import type { TableRow } from "@/board/types";

export type TransactionRow = Pick<
  TableRow<"transactions">,
  "id" | "kind" | "week" | "occurred_at" | "team_ids" | "faab_moves" | "waiver_bid"
>;
export type TransactionMoveRow = Pick<
  TableRow<"transaction_moves">,
  "transaction_id" | "sleeper_player_id" | "team_id" | "action"
>;
export type SeasonScoreRow = Pick<
  TableRow<"team_week_scores">,
  "week" | "team_id" | "players_points"
>;

interface SupabaseResult<T> {
  data: T[] | null;
  error: { message: string } | null;
}

async function unwrap<T>(
  query: PromiseLike<SupabaseResult<T>>,
  label: string,
): Promise<T[]> {
  const { data, error } = await query;
  if (error !== null) {
    throw new Error(`${label}: ${error.message}`);
  }
  return data ?? [];
}

export interface PlayerTransactions {
  transactions: TransactionRow[];
  /** Every move of every transaction the player was in — his own and the other players'. */
  moves: TransactionMoveRow[];
}

/**
 * Everything that has happened to one player this season, in two hops: the transactions his
 * own moves name, then every row of those transactions so a trade entry can name the other
 * players and the FAAB that moved with him. `raw` is never selected.
 */
export async function fetchPlayerTransactions(
  client: BoardClient,
  seasonId: number,
  sleeperPlayerId: string,
): Promise<PlayerTransactions> {
  const own = await unwrap<Pick<TransactionMoveRow, "transaction_id">>(
    client
      .from("transaction_moves")
      .select("transaction_id")
      .eq("season_id", seasonId)
      .eq("sleeper_player_id", sleeperPlayerId),
    "transaction_moves",
  );
  const ids = [...new Set(own.map((row) => row.transaction_id))];
  if (ids.length === 0) {
    return { transactions: [], moves: [] };
  }
  const [transactions, moves] = await Promise.all([
    unwrap<TransactionRow>(
      client
        .from("transactions")
        .select("id, kind, week, occurred_at, team_ids, faab_moves, waiver_bid")
        .in("id", ids),
      "transactions",
    ),
    unwrap<TransactionMoveRow>(
      client
        .from("transaction_moves")
        .select("transaction_id, sleeper_player_id, team_id, action")
        .in("transaction_id", ids),
      "transaction_moves",
    ),
  ]);
  return { transactions, moves };
}

/** Every week's score rows for the season: one per team per week, each a nine-entry map. */
export function fetchSeasonScores(
  client: BoardClient,
  seasonId: number,
): Promise<SeasonScoreRow[]> {
  return unwrap<SeasonScoreRow>(
    client
      .from("team_week_scores")
      .select("week, team_id, players_points")
      .eq("season_id", seasonId),
    "team_week_scores",
  );
}
```

`apps/web/src/player/queryKeys.ts`:

```ts
/** The player card's keys. Every key starts with `"player"`. */
export const playerKeys = {
  all: ["player"] as const,
  transactions: (seasonId: number, sleeperPlayerId: string) =>
    ["player", "transactions", seasonId, sleeperPlayerId] as const,
  seasonScores: (seasonId: number) =>
    ["player", "season_scores", seasonId] as const,
  directory: (sleeperPlayerIds: readonly string[]) =>
    ["player", "directory", [...new Set(sleeperPlayerIds)].sort()] as const,
};
```

- [ ] **Step 4: Typecheck**

Run: `pnpm --filter @ultimate-guillotine/web exec tsc --noEmit`
Expected: errors only where `RosterPlayer` literals lack the two new fields — `derive/join.ts` and the test fixture builders. Those are Task 2's and Task 3's work; everything else compiles.

- [ ] **Step 5: Commit** (typecheck red is expected until Task 2; commit anyway so the types land as one change)

```bash
git add apps/web/src/board/types.ts apps/web/src/board/fetchers.ts apps/web/src/board/queryKeys.ts apps/web/src/player/fetchers.ts apps/web/src/player/queryKeys.ts
git commit -m "feat(web): type the draft picks and transaction tables, and fetch them"
```

---

### Task 2: The drafted-here rule in the join

**Files:**
- Create: `apps/web/src/board/derive/draft.ts`, `apps/web/src/board/derive/draft.test.ts`
- Modify: `apps/web/src/board/derive/join.ts`, `apps/web/src/board/derive/join.test.ts`
- Modify: `apps/web/src/board/derive/position.ts`
- Modify: `apps/web/src/board/useBoardData.ts`
- Modify: `apps/web/src/app/board/BoardPage.test.tsx`, `apps/web/src/board/components/TeamCard.test.tsx`, `apps/web/src/board/components/PositionView.test.tsx` (fixture builders only)

**Interfaces:**
- Produces: `indexDraftPicks(rows) -> Map<string, DraftPickInfo>`; `draftedHere(pick, teamId) -> boolean`; `ordinal(n) -> string`; `AuctionContext`; `auctionContext(pick, picks) -> AuctionContext`; `auctionContextLine(context) -> string`; `BoardRawData.draftPicks`; `PositionPlayer.draft` / `.draftedHere`; `BoardDataResult.draftPicks: DraftPickRow[]`, `BoardDataResult.memberIdByTeamId: ReadonlyMap<number, number>`.

- [ ] **Step 1: Write the failing derive tests**

`apps/web/src/board/derive/draft.test.ts`:

```ts
/**
 * Map lookups and arithmetic over plain rows: no DOM.
 *
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { DraftPickRow } from "../fetchers";
import {
  auctionContext,
  auctionContextLine,
  draftedHere,
  indexDraftPicks,
  ordinal,
} from "./draft";

const pick = (
  over: Partial<DraftPickRow> & { sleeper_player_id: string; amount: number },
): DraftPickRow => ({
  team_id: 7,
  pick_no: 1,
  round: 1,
  position: "RB",
  drafted_at: "2026-09-07T23:01:30.433Z",
  ...over,
});

const PICKS = [
  pick({ sleeper_player_id: "a", amount: 80, pick_no: 1 }),
  pick({ sleeper_player_id: "b", amount: 61, pick_no: 2, team_id: 8 }),
  pick({ sleeper_player_id: "c", amount: 61, pick_no: 3, position: "WR" }),
  pick({ sleeper_player_id: "d", amount: 12, pick_no: 4 }),
  pick({ sleeper_player_id: "e", amount: 1, pick_no: 5, position: "K" }),
];

describe("indexDraftPicks", () => {
  it("keys every pick by its player, carrying the team and the price", () => {
    const index = indexDraftPicks(PICKS);
    expect(index.get("b")).toEqual({
      teamId: 8,
      amount: 61,
      pickNo: 2,
      round: 1,
      position: "RB",
      draftedAt: "2026-09-07T23:01:30.433Z",
    });
    expect(index.size).toBe(5);
  });
});

describe("draftedHere", () => {
  it("is true only when the pick belongs to the row's team", () => {
    const index = indexDraftPicks(PICKS);
    expect(draftedHere(index.get("a") ?? null, 7)).toBe(true);
    expect(draftedHere(index.get("b") ?? null, 7)).toBe(false);
  });

  it("is false for an undrafted player", () => {
    expect(draftedHere(null, 7)).toBe(false);
  });
});

describe("ordinal", () => {
  it("spells the English suffixes, teens included", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101, 111].map(ordinal)).toEqual(
      ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "101st", "111th"],
    );
  });
});

describe("auctionContext", () => {
  const index = indexDraftPicks(PICKS);
  const context = (id: string) =>
    auctionContext(index.get(id) as NonNullable<ReturnType<typeof index.get>>, index.values());

  it("ranks by price overall and within the position, as competition ranks", () => {
    expect(context("a")).toEqual({
      overallRank: 1,
      pickCount: 5,
      position: "RB",
      positionRank: 1,
      positionCount: 3,
      positionAverage: 51,
    });
    // b and c share $61: both 2nd overall, and the next price is 4th.
    expect(context("b").overallRank).toBe(2);
    expect(context("c").overallRank).toBe(2);
    expect(context("d").overallRank).toBe(4);
  });

  it("ranks within the position only against that position", () => {
    expect(context("c")).toMatchObject({ position: "WR", positionRank: 1, positionCount: 1, positionAverage: 61 });
    expect(context("d")).toMatchObject({ positionRank: 3, positionCount: 3 });
  });

  it("rounds the position average to the dollar", () => {
    // RB prices 80, 61, 12: 153 / 3 = 51 exactly; K is 1 alone.
    expect(context("e").positionAverage).toBe(1);
    const skewed = indexDraftPicks([
      pick({ sleeper_player_id: "x", amount: 10 }),
      pick({ sleeper_player_id: "y", amount: 11 }),
      pick({ sleeper_player_id: "z", amount: 11 }),
    ]);
    expect(
      auctionContext(skewed.get("x") as NonNullable<ReturnType<typeof skewed.get>>, skewed.values())
        .positionAverage,
    ).toBe(11);
  });

  it("has no position rank when the pick carries no position", () => {
    const bare = indexDraftPicks([pick({ sleeper_player_id: "n", amount: 5, position: null })]);
    expect(auctionContext(bare.get("n") as NonNullable<ReturnType<typeof bare.get>>, bare.values()))
      .toMatchObject({ position: null, positionRank: null, positionCount: 0, positionAverage: null });
  });
});

describe("auctionContextLine", () => {
  it("reads as the spec's example", () => {
    expect(
      auctionContextLine({
        overallRank: 9,
        pickCount: 162,
        position: "RB",
        positionRank: 4,
        positionCount: 40,
        positionAverage: 22,
      }),
    ).toBe("9th priciest pick · 4th RB · RB average $22");
  });

  it("stops after the overall rank when there is no position", () => {
    expect(
      auctionContextLine({
        overallRank: 150,
        pickCount: 162,
        position: null,
        positionRank: null,
        positionCount: 0,
        positionAverage: null,
      }),
    ).toBe("150th priciest pick");
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm --filter @ultimate-guillotine/web exec vitest run src/board/derive/draft.test.ts`
Expected: fails to resolve `./draft`.

- [ ] **Step 3: Write the derive module**

`apps/web/src/board/derive/draft.ts`:

```ts
import type { DraftPickRow } from "../fetchers";
import type { DraftPickInfo } from "../types";

/** The season's picks keyed by player, in the shape a roster row carries. */
export function indexDraftPicks(
  rows: readonly DraftPickRow[],
): Map<string, DraftPickInfo> {
  const index = new Map<string, DraftPickInfo>();
  for (const row of rows) {
    index.set(row.sleeper_player_id, {
      teamId: row.team_id,
      amount: row.amount,
      pickNo: row.pick_no,
      round: row.round,
      position: row.position,
      draftedAt: row.drafted_at,
    });
  }
  return index;
}

/**
 * The one-line rule behind the mark: the pick belongs to the team whose row this is. A
 * player traded away and back is "still here" too — the journey tells that story.
 */
export function draftedHere(pick: DraftPickInfo | null, teamId: number): boolean {
  return pick !== null && pick.teamId === teamId;
}

/** `1st`, `2nd`, `3rd`, `4th`, … with the teens as `th`. */
export function ordinal(n: number): string {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
}

export interface AuctionContext {
  /** Competition rank by price over the whole auction: tied prices share the higher rank. */
  overallRank: number;
  pickCount: number;
  position: string | null;
  /** The same rank among picks at the same position; null when the pick has no position. */
  positionRank: number | null;
  positionCount: number;
  /** The mean price at the position, rounded to the dollar; null when there is no position. */
  positionAverage: number | null;
}

/** Where a pick's price sat in the auction, overall and at its position. */
export function auctionContext(
  pick: DraftPickInfo,
  picks: Iterable<DraftPickInfo>,
): AuctionContext {
  let pickCount = 0;
  let pricier = 0;
  let positionCount = 0;
  let positionPricier = 0;
  let positionTotal = 0;
  for (const other of picks) {
    pickCount += 1;
    if (other.amount > pick.amount) pricier += 1;
    if (pick.position !== null && other.position === pick.position) {
      positionCount += 1;
      positionTotal += other.amount;
      if (other.amount > pick.amount) positionPricier += 1;
    }
  }
  const hasPosition = pick.position !== null && positionCount > 0;
  return {
    overallRank: pricier + 1,
    pickCount,
    position: pick.position,
    positionRank: hasPosition ? positionPricier + 1 : null,
    positionCount,
    positionAverage: hasPosition ? Math.round(positionTotal / positionCount) : null,
  };
}

/** The card's context line: `9th priciest pick · 4th RB · RB average $22`. */
export function auctionContextLine(context: AuctionContext): string {
  const parts = [`${ordinal(context.overallRank)} priciest pick`];
  if (
    context.position !== null &&
    context.positionRank !== null &&
    context.positionAverage !== null
  ) {
    parts.push(`${ordinal(context.positionRank)} ${context.position}`);
    parts.push(`${context.position} average $${context.positionAverage}`);
  }
  return parts.join(" · ");
}
```

- [ ] **Step 4: Run the derive tests**

Run: `pnpm --filter @ultimate-guillotine/web exec vitest run src/board/derive/draft.test.ts`
Expected: PASS.

- [ ] **Step 5: Write the failing join tests**

Append to `apps/web/src/board/derive/join.test.ts` (inside the file, after the existing `raw` builder add `draftPicks: []` to its defaults — see Step 6 — then add this block at the end):

```ts
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
      { sleeper_player_id: "4046", slot: "starter", slot_index: 0, lineup_position: "QB" },
    ];
    const [team] = joinBoardTeams(
      raw({
        draftPicks: picks,
        teamSeasonState: [
          { ...raw().teamSeasonState[0], is_eliminated: true, eliminated_week: 2 },
        ],
        finalRosters: [
          { team_id: 7, eliminated_week: 2, holdings: frozen, frozen_at: "2026-09-20T00:00:00Z" },
        ],
      }),
    );
    expect(team.isRosterFrozen).toBe(true);
    expect(team.roster[0]?.draftedHere).toBe(true);
  });
});
```

- [ ] **Step 6: Extend the join, the position row, and every fixture builder**

In `apps/web/src/board/derive/join.ts`: import `indexDraftPicks, draftedHere` from `./draft` and `DraftPickRow` from `../fetchers`; add to `BoardRawData` after `finalRosters`:

```ts
  /** The season's auction, one row per pick. Empty before the draft or the first sync. */
  draftPicks: DraftPickRow[];
```

In `joinBoardTeams`, after `pointsByPlayerId`:

```ts
  const draftByPlayerId = indexDraftPicks(raw.draftPicks);
```

In `buildRosterPlayer`, before the `return`, add `const draft = draftByPlayerId.get(holding.sleeper_player_id) ?? null;` and two fields after `injuryStatus`:

```ts
      draft,
      draftedHere: draftedHere(draft, teamId),
```

In `apps/web/src/board/derive/position.ts`, add to `PositionPlayer` after `injuryStatus`:

```ts
  /** The pick and the rule, exactly as the roster row carries them. */
  draft: DraftPickInfo | null;
  draftedHere: boolean;
```

import `DraftPickInfo` from `../types`, and in `toPositionPlayer` add `draft: player.draft, draftedHere: player.draftedHere,`.

In `apps/web/src/board/derive/join.test.ts`'s `raw` builder add `draftPicks: [],` before `...over`. In every `player` fixture builder — `apps/web/src/app/board/BoardPage.test.tsx`, `apps/web/src/board/components/TeamCard.test.tsx`, `apps/web/src/board/components/PositionView.test.tsx`, and any other file `grep -l "livePoints: null" apps/web/src --include=*.test.tsx --include=*.test.ts` names — add `draft: null, draftedHere: false,` before `...over`.

- [ ] **Step 7: Load the picks with the board**

In `apps/web/src/board/useBoardData.ts`: import `fetchDraftPicks` and `type DraftPickRow`; add to `BoardDataResult` after `rosterPositions`:

```ts
  /** The season's auction, whole; the card's context line is computed from it. */
  draftPicks: DraftPickRow[];
  /** `teams.id` -> `members.id`, for matching a Sleeper trade to a registered one. */
  memberIdByTeamId: ReadonlyMap<number, number>;
```

After the `finalRosters` query:

```ts
  const draftPicks = useQuery({
    queryKey: boardKeys.draftPicks(seasonId ?? 0),
    queryFn: () => fetchDraftPicks(boardClient, seasonId as number),
    enabled: hasSeason,
    ...shared,
    // The auction is a fact that changes once a year. Window focus still refetches it.
    staleTime: Number.POSITIVE_INFINITY,
    refetchInterval: false as const,
  });
```

Add `draftPicks: draftPicks.data ?? []` to the `joinBoardTeams` call and `draftPicks.data` to its deps; add `["Draft", draftPicks]` to `sections`; add

```ts
  const memberIdByTeamId = useMemo(
    () => new Map((teams.data ?? []).map((team) => [team.id, team.member_id])),
    [teams.data],
  );
```

and return `draftPicks: draftPicks.data ?? [], memberIdByTeamId,`. In `BoardPage.test.tsx`'s `result` builder add `draftPicks: [], memberIdByTeamId: new Map(),`.

- [ ] **Step 8: Run the affected suites and the gates**

Run: `pnpm --filter @ultimate-guillotine/web exec tsc --noEmit && pnpm --filter @ultimate-guillotine/web exec vitest run src/board && pnpm lint`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add apps/web/src/board apps/web/src/app/board/BoardPage.test.tsx
git commit -m "feat(web): every roster row knows its auction pick and whether it is still home"
```

---

### Task 3: The mark and the name, in both roster rows

**Files:**
- Create: `apps/web/src/board/components/DraftedMark.tsx`
- Create: `apps/web/src/board/components/PlayerName.tsx`, `apps/web/src/board/components/PlayerName.test.tsx`
- Modify: `apps/web/src/board/components/RosterPanel.tsx`, `TeamCard.tsx`, `PositionView.tsx`, `TeamCard.test.tsx`, `PositionView.test.tsx`
- Modify: `apps/web/src/app/board/BoardPage.tsx`

**Interfaces:**
- Produces: `DRAFTED_HERE_LABEL`, `draftedHereDescription(ownerName, amount)`, `DraftedMark({ ownerName, amount })`; `PlayerName({ player, ownerName, onOpen })`; `RosterPanel` and `TeamCard` and `PositionView` gain `onOpenPlayer: (sleeperPlayerId: string) => void`, and `RosterPanel` gains `ownerName: string`.

- [ ] **Step 1: Write the failing component test**

`apps/web/src/board/components/PlayerName.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RosterPlayer } from "../types";
import { DRAFTED_HERE_LABEL, draftedHereDescription } from "./DraftedMark";
import { PlayerName } from "./PlayerName";

const player = (over: Partial<RosterPlayer> = {}): RosterPlayer => ({
  sleeperPlayerId: "9493",
  fullName: "Puka Nacua",
  position: "WR",
  nflTeam: "LAR",
  slot: "starter",
  slotIndex: 3,
  lineupPosition: "WR",
  projectedPoints: 14.1,
  livePoints: null,
  injuryStatus: null,
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

describe("PlayerName", () => {
  it("is a button that opens a dialog for this player", () => {
    const onOpen = vi.fn();
    render(<PlayerName player={player()} ownerName="Ray Regime" onOpen={onOpen} />);
    const name = screen.getByRole("button", { name: "Puka Nacua" });
    expect(name).toHaveAttribute("aria-haspopup", "dialog");
    fireEvent.click(name);
    expect(onOpen).toHaveBeenCalledWith("9493");
  });

  it("carries the mark, with the drafter and the price behind it, when he is still home", () => {
    render(<PlayerName player={player()} ownerName="Ray Regime" onOpen={vi.fn()} />);
    const mark = screen.getByRole("button", { name: DRAFTED_HERE_LABEL });
    expect(mark).toHaveAttribute("data-drafted-here");
    expect(mark).toHaveAccessibleDescription(draftedHereDescription("Ray Regime", 53));
  });

  it("carries no mark for a player another team drafted", () => {
    render(
      <PlayerName player={player({ draftedHere: false })} ownerName="Ray Regime" onOpen={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: DRAFTED_HERE_LABEL })).not.toBeInTheDocument();
  });

  it("carries no mark for an undrafted pickup", () => {
    render(
      <PlayerName player={player({ draft: null, draftedHere: false })} ownerName="Ray Regime" onOpen={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: DRAFTED_HERE_LABEL })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm --filter @ultimate-guillotine/web exec vitest run src/board/components/PlayerName.test.tsx`
Expected: fails to resolve `./PlayerName`.

- [ ] **Step 3: Write the two components**

`apps/web/src/board/components/DraftedMark.tsx`:

```tsx
import { Anchor } from "lucide-react";

import { ExplainedBadge } from "@/components/explained-badge";

/** The mark's accessible name; the sentence behind it is `draftedHereDescription`. */
export const DRAFTED_HERE_LABEL = "Drafted here";

/** What the tooltip says, spelled once so the row and its tests cannot drift. */
export function draftedHereDescription(ownerName: string, amount: number): string {
  return `Drafted by ${ownerName} for $${amount}`;
}

/**
 * The anchor beside a player still on the team that drafted him. Ben (2026-09-10) chose a small
 * glyph with a tooltip over the price itself on the row. An `ExplainedBadge`, so a tap opens the
 * sentence on a phone and a screen reader gets it either way; the icon is a one-line swap.
 */
export function DraftedMark({
  ownerName,
  amount,
}: {
  ownerName: string;
  amount: number;
}) {
  return (
    <ExplainedBadge
      data-drafted-here
      aria-label={DRAFTED_HERE_LABEL}
      description={draftedHereDescription(ownerName, amount)}
      className="-my-2 ml-1 inline-flex min-h-[44px] shrink-0 items-center rounded-md px-0.5 text-muted-foreground"
    >
      <Anchor aria-hidden="true" className="h-3 w-3" />
    </ExplainedBadge>
  );
}
```

`apps/web/src/board/components/PlayerName.tsx`:

```tsx
import { cn } from "@/lib/utils";

import type { RosterPlayer } from "../types";
import { DraftedMark } from "./DraftedMark";

/** The ring every bare `<button>` on the board carries. */
const FOCUS_RING_CLASS =
  "ring-offset-background focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

export type PlayerNameSource = Pick<
  RosterPlayer,
  "sleeperPlayerId" | "fullName" | "draft" | "draftedHere"
>;

/**
 * A player's name as the one control that opens his card, with the drafted-here mark beside it.
 *
 * Shared by the roster panel and the position view so the mark and the tap live in one place.
 * Both are siblings inside a flex span — the mark is its own button and may not nest inside
 * the name's — and the name is the part that truncates.
 */
export function PlayerName({
  player,
  ownerName,
  onOpen,
  className,
}: {
  player: PlayerNameSource;
  ownerName: string;
  onOpen: (sleeperPlayerId: string) => void;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex min-w-0 items-center", className)}>
      <button
        type="button"
        aria-haspopup="dialog"
        onClick={() => onOpen(player.sleeperPlayerId)}
        className={cn(
          "min-w-0 truncate rounded-sm text-left font-medium underline-offset-2 hover:underline",
          FOCUS_RING_CLASS,
        )}
      >
        {player.fullName}
      </button>
      {player.draftedHere && player.draft !== null ? (
        <DraftedMark ownerName={ownerName} amount={player.draft.amount} />
      ) : null}
    </span>
  );
}
```

- [ ] **Step 4: Run the component test**

Run: `pnpm --filter @ultimate-guillotine/web exec vitest run src/board/components/PlayerName.test.tsx`
Expected: PASS.

- [ ] **Step 5: Use it in the roster panel**

In `apps/web/src/board/components/RosterPanel.tsx`: import `PlayerName`. `PlayerRowProps` gains `ownerName: string; onOpenPlayer: (sleeperPlayerId: string) => void;`. In `PlayerRow`, replace the left span:

```tsx
      <span className="flex min-w-0 items-center gap-2">
        <PlayerName player={player} ownerName={ownerName} onOpen={onOpenPlayer} />
        {meta === "" ? null : (
          <span className="shrink-0 text-muted-foreground">{meta}</span>
        )}
        <InjuryTag status={player.injuryStatus} />
      </span>
```

and change the `<li>` class from `items-baseline` to `items-center`. `RosterPanelProps` gains the same two props, and both `<PlayerRow>` call sites pass `ownerName={ownerName} onOpenPlayer={onOpenPlayer}`.

In `apps/web/src/board/components/TeamCard.tsx`: `TeamCardProps` gains `onOpenPlayer: (sleeperPlayerId: string) => void;` (destructure it), and the `<RosterPanel>` call gains `ownerName={team.ownerName} onOpenPlayer={onOpenPlayer}`.

- [ ] **Step 6: Use it in the position view**

In `apps/web/src/board/components/PositionView.tsx`: import `PlayerName`. `PositionTeamRowProps` and `PositionViewProps` gain `onOpenPlayer: (sleeperPlayerId: string) => void;`; thread it from `PositionView` into every `PositionTeamRow`, and from the row into the `<RosterPanel>` (with `ownerName={row.ownerName}`). Replace the inline row's name span:

```tsx
                    <span className="flex min-w-0 flex-1 items-center gap-1">
                      <PlayerName
                        player={player}
                        ownerName={row.ownerName}
                        onOpen={onOpenPlayer}
                      />
                      <span className="shrink-0 text-muted-foreground tabular-nums">
                        {/* the existing live / projection markup, unchanged */}
                      </span>
                    </span>
```

- [ ] **Step 7: Thread a stable opener from the page**

In `apps/web/src/app/board/BoardPage.tsx`, for now pass `onOpenPlayer={noopOpen}` where `const noopOpen = useCallback((_id: string) => undefined, []);` — Task 7 replaces it with the real handler. Update the render helpers in `TeamCard.test.tsx` and `PositionView.test.tsx` to pass `onOpenPlayer={noop}`.

- [ ] **Step 8: Run the gates**

Run: `pnpm --filter @ultimate-guillotine/web exec tsc --noEmit && pnpm test:web && pnpm lint`
Expected: PASS. If a `TeamCard` test asserts a row's exact `textContent`, the mark's screen-reader sentence is not in it (fixtures default to `draftedHere: false`), so nothing changes.

- [ ] **Step 9: Commit**

```bash
git add apps/web/src/board apps/web/src/app/board/BoardPage.tsx
git commit -m "feat(web): the drafted-here mark, and every player's name opens his card"
```

---

### Task 4: Points and the date line

**Files:**
- Create: `apps/web/src/player/derive/points.ts` (+ `.test.ts`)
- Create: `apps/web/src/player/derive/dateLine.ts` (+ `.test.ts`)

**Interfaces:**
- Produces: `seasonPoints(rows, sleeperPlayerId) -> { total: number; weeks: number }`; `formatDateLine(iso, week, options?) -> string` (`Sep 9 · Wk 1`, or `Sep 7` with `week === null`); `ROSTERED_WEEKS_CAPTION(weeks)`.

- [ ] **Step 1: Write the failing tests**

`apps/web/src/player/derive/points.test.ts`:

```ts
/** @vitest-environment node */
import { describe, expect, it } from "vitest";

import { rosteredWeeksCaption, seasonPoints } from "./points";

const rows = [
  { week: 1, team_id: 7, players_points: { "9493": 12.4, "4046": 20.1 } },
  { week: 2, team_id: 7, players_points: { "9493": 0 } },
  { week: 3, team_id: 9, players_points: { "9493": 7.5 } },
  // The same player named twice in one week: counted once.
  { week: 3, team_id: 7, players_points: { "9493": 7.5 } },
  { week: 4, team_id: 7, players_points: { "4046": 3 } },
];

describe("seasonPoints", () => {
  it("sums the weeks the player was rostered and counts them", () => {
    expect(seasonPoints(rows, "9493")).toEqual({ total: 19.9, weeks: 3 });
  });

  it("is zero over no weeks for a player nobody has rostered", () => {
    expect(seasonPoints(rows, "0000")).toEqual({ total: 0, weeks: 0 });
  });

  it("drops a value that is not a finite number", () => {
    const junk = [{ week: 1, team_id: 7, players_points: { "9493": Number.NaN } }];
    expect(seasonPoints(junk, "9493")).toEqual({ total: 0, weeks: 0 });
  });
});

describe("rosteredWeeksCaption", () => {
  it("counts the weeks in words", () => {
    expect(rosteredWeeksCaption(1)).toBe("in 1 rostered week");
    expect(rosteredWeeksCaption(3)).toBe("in 3 rostered weeks");
  });
});
```

`apps/web/src/player/derive/dateLine.test.ts`:

```ts
/** @vitest-environment node */
import { describe, expect, it } from "vitest";

import { formatDateLine } from "./dateLine";

const OPTIONS = { locales: "en-US", timeZone: "America/Chicago" };

describe("formatDateLine", () => {
  it("is the day and the week, in the trade page's voice", () => {
    expect(formatDateLine("2026-09-08T14:01:40Z", 1, OPTIONS)).toBe("Sep 8 · Wk 1");
  });

  it("is the day alone when there is no week", () => {
    expect(formatDateLine("2026-09-07T23:01:30.433Z", null, OPTIONS)).toBe("Sep 7");
  });

  it("falls back to the week alone for an unparseable instant", () => {
    expect(formatDateLine("not a date", 4, OPTIONS)).toBe("Wk 4");
    expect(formatDateLine("not a date", null, OPTIONS)).toBe("");
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pnpm --filter @ultimate-guillotine/web exec vitest run src/player/derive`
Expected: both files fail to resolve their module.

- [ ] **Step 3: Write the modules**

`apps/web/src/player/derive/points.ts`:

```ts
import type { SeasonScoreRow } from "../fetchers";

export interface SeasonPoints {
  total: number;
  /** How many weeks' rows named the player — the caption's honest denominator. */
  weeks: number;
}

/**
 * The player's points over the weeks he was on any roster, from `team_week_scores`.
 *
 * With nine roster slots and no bench, every rostered player is a starter and every week's
 * row names him, so this is the season to date for the weeks he was in the league. A week he
 * sat unrostered is a gap the caption owns up to rather than a zero. One value per week: a
 * player who appears in two teams' rows for one week — a trade mid-sync — counts once.
 */
export function seasonPoints(
  rows: readonly SeasonScoreRow[],
  sleeperPlayerId: string,
): SeasonPoints {
  const byWeek = new Map<number, number>();
  for (const row of rows) {
    const value: unknown = row.players_points?.[sleeperPlayerId];
    if (typeof value !== "number" || !Number.isFinite(value)) continue;
    if (!byWeek.has(row.week)) byWeek.set(row.week, value);
  }
  let total = 0;
  for (const value of byWeek.values()) total += value;
  return { total: Math.round(total * 100) / 100, weeks: byWeek.size };
}

/** `in 3 rostered weeks` — the caption under the season figure. */
export function rosteredWeeksCaption(weeks: number): string {
  return `in ${weeks} rostered ${weeks === 1 ? "week" : "weeks"}`;
}
```

`apps/web/src/player/derive/dateLine.ts`:

```ts
import type { TimeFormatOptions } from "@/board/derive/time";

const SEPARATOR = " · ";

/**
 * The journey's date voice: `Sep 8 · Wk 1`, the day in the viewer's own timezone and Sleeper's
 * own week. The draft entry has no week and reads `Sep 7`. An instant that will not parse
 * loses its day rather than printing `Invalid Date`.
 */
export function formatDateLine(
  iso: string,
  week: number | null,
  options: TimeFormatOptions = {},
): string {
  const parts: string[] = [];
  const at = Date.parse(iso);
  if (Number.isFinite(at)) {
    parts.push(
      new Intl.DateTimeFormat(options.locales, {
        month: "short",
        day: "numeric",
        timeZone: options.timeZone,
      }).format(at),
    );
  }
  if (week !== null) parts.push(`Wk ${week}`);
  return parts.join(SEPARATOR);
}
```

- [ ] **Step 4: Run the tests**

Run: `pnpm --filter @ultimate-guillotine/web exec vitest run src/player/derive`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/player/derive/points.ts apps/web/src/player/derive/points.test.ts apps/web/src/player/derive/dateLine.ts apps/web/src/player/derive/dateLine.test.ts
git commit -m "feat(web): season points over rostered weeks, and the journey's date voice"
```

---

### Task 5: The journey and the trade match

**Files:**
- Create: `apps/web/src/player/derive/journey.ts` (+ `.test.ts`)

**Interfaces:**
- Consumes: `TransactionRow`, `TransactionMoveRow`, `DraftPickInfo`, `CatalogTrade`.
- Produces: `JourneyEntry` union; `RegisteredLink { key, tradeCode, announcement, rescinded }`; `MATCH_WINDOW_MS`; `buildJourney(input: JourneyInput) -> JourneyEntry[]`; `matchRegisteredTrades(...)`.

- [ ] **Step 1: Write the failing tests**

`apps/web/src/player/derive/journey.test.ts`:

```ts
/** @vitest-environment node */
import { describe, expect, it } from "vitest";

import type { CatalogTrade } from "@/history/types";

import type { TransactionMoveRow, TransactionRow } from "../fetchers";
import { buildJourney, MATCH_WINDOW_MS, type JourneyInput } from "./journey";

const ME = "9493";
const PICK = {
  teamId: 1,
  amount: 53,
  pickNo: 1,
  round: 1,
  position: "WR",
  draftedAt: "2026-09-07T23:01:30.433Z",
};

const tx = (over: Partial<TransactionRow> & { id: number; kind: TransactionRow["kind"] }): TransactionRow => ({
  week: 1,
  occurred_at: "2026-09-08T14:01:40Z",
  team_ids: [1, 16],
  faab_moves: [],
  waiver_bid: null,
  ...over,
});

const move = (
  transaction_id: number,
  sleeper_player_id: string,
  team_id: number,
  action: TransactionMoveRow["action"],
): TransactionMoveRow => ({ transaction_id, sleeper_player_id, team_id, action });

const registered = (over: Partial<CatalogTrade> & { key: string }): CatalogTrade => ({
  season: 2026,
  week: 1,
  occurredOn: null,
  tradeType: "trade",
  structure: "2-team",
  parties: [
    { memberId: 101, label: "Ben", resolved: true },
    { memberId: 116, label: "Ryland", resolved: true },
  ],
  partyCount: 2,
  assets: [
    { kind: "player", playerId: ME, name: "Puka Nacua", position: "WR", fromParty: 0, toParty: 1 },
  ],
  confidence: "high",
  announcement: "Puka for Bowers plus 65",
  registeredAt: "2026-09-08T13:30:00Z",
  announcedBy: "Ben",
  sourceLabel: "T-2026-003",
  registered: true,
  rescinded: false,
  unresolvedParties: 0,
  ...over,
});

const input = (over: Partial<JourneyInput> = {}): JourneyInput => ({
  sleeperPlayerId: ME,
  season: 2026,
  pick: PICK,
  transactions: [],
  moves: [],
  registered: [],
  memberIdByTeamId: new Map([
    [1, 101],
    [16, 116],
    [8, 108],
  ]),
  ...over,
});

describe("buildJourney", () => {
  it("starts with the draft, dated by the auction", () => {
    expect(buildJourney(input())).toEqual([
      { kind: "drafted", key: "draft", at: PICK.draftedAt, week: null, teamId: 1, amount: 53, pickNo: 1 },
    ]);
  });

  it("has no draft entry for an undrafted pickup", () => {
    expect(buildJourney(input({ pick: null }))).toEqual([]);
  });

  it("reads a trade as from one team to another, with the other players and the FAAB", () => {
    const trade = tx({
      id: 5,
      kind: "trade",
      faab_moves: [{ amount: 65, from_team_id: 1, to_team_id: 16 }],
    });
    const moves = [
      move(5, ME, 16, "add"),
      move(5, ME, 1, "drop"),
      move(5, "12534", 1, "add"),
      move(5, "12534", 16, "drop"),
    ];
    const [, entry] = buildJourney(input({ transactions: [trade], moves }));
    expect(entry).toEqual({
      kind: "traded",
      key: "tx:5",
      at: "2026-09-08T14:01:40Z",
      week: 1,
      fromTeamId: 1,
      toTeamId: 16,
      others: [{ sleeperPlayerId: "12534", fromTeamId: 16, toTeamId: 1 }],
      faab: [{ amount: 65, fromTeamId: 1, toTeamId: 16 }],
      registered: null,
    });
  });

  it("reads a claim with its bid, a drop, a pickup, and a commissioner move", () => {
    const transactions = [
      tx({ id: 1, kind: "free_agent", week: 2, occurred_at: "2026-09-15T00:00:00Z", team_ids: [8] }),
      tx({ id: 2, kind: "waiver", week: 3, occurred_at: "2026-09-23T00:00:00Z", team_ids: [16], waiver_bid: 12 }),
      tx({ id: 3, kind: "waiver", week: 3, occurred_at: "2026-09-23T01:00:00Z", team_ids: [8] }),
      tx({ id: 4, kind: "commissioner", week: 4, occurred_at: "2026-09-30T00:00:00Z", team_ids: [1] }),
    ];
    const moves = [
      move(1, ME, 8, "drop"),
      move(2, ME, 16, "add"),
      move(3, ME, 8, "drop"),
      move(3, "0000", 8, "add"),
      move(4, ME, 1, "add"),
    ];
    const entries = buildJourney(input({ pick: null, transactions, moves }));
    expect(entries.map((e) => e.kind)).toEqual(["dropped", "claimed", "dropped", "commissioner"]);
    expect(entries[0]).toMatchObject({ teamId: 8, week: 2 });
    expect(entries[1]).toMatchObject({ teamId: 16, bid: 12 });
    expect(entries[3]).toMatchObject({ teamId: 1, action: "add" });
  });

  it("reads a free-agent add as added", () => {
    const pickup = tx({ id: 9, kind: "free_agent", team_ids: [8] });
    const entries = buildJourney(input({ pick: null, transactions: [pickup], moves: [move(9, ME, 8, "add")] }));
    expect(entries).toEqual([
      { kind: "added", key: "tx:9", at: "2026-09-08T14:01:40Z", week: 1, teamId: 8 },
    ]);
  });

  it("orders entries by time, the draft first", () => {
    const later = tx({ id: 2, kind: "free_agent", week: 3, occurred_at: "2026-09-23T00:00:00Z", team_ids: [8] });
    const earlier = tx({ id: 1, kind: "free_agent", week: 2, occurred_at: "2026-09-15T00:00:00Z", team_ids: [8] });
    const entries = buildJourney(
      input({ transactions: [later, earlier], moves: [move(2, ME, 8, "add"), move(1, ME, 8, "drop")] }),
    );
    expect(entries.map((e) => e.key)).toEqual(["draft", "tx:1", "tx:2"]);
  });

  describe("matching a registered trade", () => {
    const trade = tx({ id: 5, kind: "trade" });
    const moves = [move(5, ME, 16, "add"), move(5, ME, 1, "drop")];

    it("attaches the registered trade with the same owners announced within the window", () => {
      const entries = buildJourney(input({ transactions: [trade], moves, registered: [registered({ key: "r1" })] }));
      expect(entries[1]).toMatchObject({
        kind: "traded",
        registered: { key: "r1", tradeCode: "T-2026-003", announcement: "Puka for Bowers plus 65", rescinded: false },
      });
      // Matched, so not also an "announced" entry.
      expect(entries).toHaveLength(2);
    });

    it("prefers the nearest announcement when two qualify, and links each once", () => {
      const near = registered({ key: "near", registeredAt: "2026-09-08T14:30:00Z", sourceLabel: "T-NEAR" });
      const far = registered({ key: "far", registeredAt: "2026-09-08T02:00:00Z", sourceLabel: "T-FAR" });
      const entries = buildJourney(input({ transactions: [trade], moves, registered: [far, near] }));
      expect(entries[1]).toMatchObject({ registered: { tradeCode: "T-NEAR" } });
      expect(entries.find((e) => e.kind === "announced")).toMatchObject({ registered: { tradeCode: "T-FAR" } });
    });

    it("does not match outside the window, a different owner set, an unresolved party, or another season", () => {
      const late = registered({ key: "late", registeredAt: new Date(Date.parse("2026-09-08T14:01:40Z") + MATCH_WINDOW_MS + 1000).toISOString() });
      const otherOwners = registered({ key: "owners", parties: [{ memberId: 101, label: "Ben", resolved: true }, { memberId: 108, label: "Nick", resolved: true }] });
      const unresolved = registered({ key: "unresolved", parties: [{ memberId: 101, label: "Ben", resolved: true }, { memberId: 999, label: "Former manager", resolved: false }] });
      const lastYear = registered({ key: "2025", season: 2025 });
      const entries = buildJourney(input({ transactions: [trade], moves, registered: [late, otherOwners, unresolved, lastYear] }));
      expect(entries[1]).toMatchObject({ kind: "traded", registered: null });
      // The three same-season unmatched ones remain as announcements; last year's is gone.
      expect(entries.filter((e) => e.kind === "announced").map((e) => e.key)).toEqual(
        expect.arrayContaining(["reg:late", "reg:owners", "reg:unresolved"]),
      );
      expect(entries.some((e) => e.key === "reg:2025")).toBe(false);
    });

    it("keeps a registered trade with no Sleeper counterpart as an announced entry", () => {
      const entries = buildJourney(input({ registered: [registered({ key: "r1" })] }));
      expect(entries[1]).toEqual({
        kind: "announced",
        key: "reg:r1",
        at: "2026-09-08T13:30:00Z",
        week: 1,
        registered: { key: "r1", tradeCode: "T-2026-003", announcement: "Puka for Bowers plus 65", rescinded: false },
      });
    });

    it("ignores a registered trade that does not name this player", () => {
      const other = registered({ key: "other", assets: [{ kind: "player", playerId: "0000", name: "Someone", position: null, fromParty: 0, toParty: 1 }] });
      expect(buildJourney(input({ registered: [other] }))).toHaveLength(1);
    });
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm --filter @ultimate-guillotine/web exec vitest run src/player/derive/journey.test.ts`
Expected: fails to resolve `./journey`.

- [ ] **Step 3: Write the module**

`apps/web/src/player/derive/journey.ts`:

```ts
import type { DraftPickInfo, FaabMoveEntry } from "@/board/types";
import type { CatalogTrade } from "@/history/types";

import type { TransactionMoveRow, TransactionRow } from "../fetchers";

/** The registered trade a Sleeper trade matched, or one with no counterpart. */
export interface RegisteredLink {
  key: string;
  tradeCode: string;
  announcement: string | null;
  rescinded: boolean;
}

export interface OtherPlayerMove {
  sleeperPlayerId: string;
  fromTeamId: number | null;
  toTeamId: number | null;
}

export interface FaabMove {
  amount: number;
  fromTeamId: number;
  toTeamId: number;
}

export type JourneyEntry =
  | { kind: "drafted"; key: string; at: string; week: null; teamId: number; amount: number; pickNo: number }
  | {
      kind: "traded";
      key: string;
      at: string;
      week: number;
      fromTeamId: number | null;
      toTeamId: number | null;
      others: OtherPlayerMove[];
      faab: FaabMove[];
      registered: RegisteredLink | null;
    }
  | { kind: "dropped"; key: string; at: string; week: number; teamId: number }
  | { kind: "claimed"; key: string; at: string; week: number; teamId: number; bid: number | null }
  | { kind: "added"; key: string; at: string; week: number; teamId: number }
  | { kind: "commissioner"; key: string; at: string; week: number; teamId: number; action: "add" | "drop" }
  | { kind: "announced"; key: string; at: string; week: number | null; registered: RegisteredLink };

export interface JourneyInput {
  sleeperPlayerId: string;
  /** The board's season year; registered trades from any other are ignored. */
  season: number;
  pick: DraftPickInfo | null;
  transactions: TransactionRow[];
  /** Every move of every transaction in `transactions`, this player's and the others'. */
  moves: TransactionMoveRow[];
  registered: CatalogTrade[];
  memberIdByTeamId: ReadonlyMap<number, number>;
}

/** How far apart a Sleeper trade and its announcement may be and still be the same deal. */
export const MATCH_WINDOW_MS = 72 * 60 * 60 * 1000;

function link(trade: CatalogTrade): RegisteredLink {
  return {
    key: trade.key,
    tradeCode: trade.sourceLabel,
    announcement: trade.announcement,
    rescinded: trade.rescinded,
  };
}

function sameSet(a: readonly number[], b: readonly number[]): boolean {
  const left = new Set(a);
  const right = new Set(b);
  if (left.size !== right.size) return false;
  for (const value of left) if (!right.has(value)) return false;
  return true;
}

/** The instant a registered trade was announced, or null when it cannot be read. */
function registeredAt(trade: CatalogTrade): number | null {
  if (trade.registeredAt === null) return null;
  const at = Date.parse(trade.registeredAt);
  return Number.isFinite(at) ? at : null;
}

/**
 * Pair Sleeper trades with registered ones: same owners, announced within the window, nearest
 * wins, each registered trade at most once. A registered trade with a party the directory
 * cannot name never matches — its owner set is unknowable.
 */
export function matchRegisteredTrades(
  trades: readonly { id: number; occurredAt: number; memberIds: number[] }[],
  registered: readonly CatalogTrade[],
): Map<number, CatalogTrade> {
  const candidates: { transactionId: number; trade: CatalogTrade; distance: number }[] = [];
  for (const trade of registered) {
    if (trade.parties.some((party) => !party.resolved)) continue;
    if (trade.parties.length !== trade.partyCount) continue;
    const announced = registeredAt(trade);
    if (announced === null) continue;
    const memberIds = trade.parties.map((party) => party.memberId);
    for (const sleeper of trades) {
      if (!sameSet(sleeper.memberIds, memberIds)) continue;
      const distance = Math.abs(sleeper.occurredAt - announced);
      if (distance > MATCH_WINDOW_MS) continue;
      candidates.push({ transactionId: sleeper.id, trade, distance });
    }
  }
  candidates.sort((a, b) => a.distance - b.distance);
  const matched = new Map<number, CatalogTrade>();
  const used = new Set<string>();
  for (const candidate of candidates) {
    if (matched.has(candidate.transactionId) || used.has(candidate.trade.key)) continue;
    matched.set(candidate.transactionId, candidate.trade);
    used.add(candidate.trade.key);
  }
  return matched;
}

function faabMoves(entries: FaabMoveEntry[]): FaabMove[] {
  const value: unknown = entries;
  if (!Array.isArray(value)) return [];
  return (value as unknown[]).flatMap((entry) => {
    if (typeof entry !== "object" || entry === null) return [];
    const move = entry as Record<string, unknown>;
    if (
      typeof move.amount !== "number" ||
      typeof move.from_team_id !== "number" ||
      typeof move.to_team_id !== "number"
    ) {
      return [];
    }
    return [{ amount: move.amount, fromTeamId: move.from_team_id, toTeamId: move.to_team_id }];
  });
}

function namesPlayer(trade: CatalogTrade, sleeperPlayerId: string): boolean {
  return trade.assets.some(
    (asset) => asset.kind === "player" && asset.playerId === sleeperPlayerId,
  );
}

/**
 * The player's season as an ordered list: drafted, then every transaction he was in, with the
 * league's own announcement attached where a registered trade matches, and the announcements
 * no Sleeper trade explains kept as entries of their own.
 */
export function buildJourney(input: JourneyInput): JourneyEntry[] {
  const entries: JourneyEntry[] = [];
  if (input.pick !== null) {
    entries.push({
      kind: "drafted",
      key: "draft",
      at: input.pick.draftedAt,
      week: null,
      teamId: input.pick.teamId,
      amount: input.pick.amount,
      pickNo: input.pick.pickNo,
    });
  }

  const movesByTransaction = new Map<number, TransactionMoveRow[]>();
  for (const move of input.moves) {
    const list = movesByTransaction.get(move.transaction_id);
    if (list === undefined) movesByTransaction.set(move.transaction_id, [move]);
    else list.push(move);
  }

  const mine = (id: number, action: "add" | "drop") =>
    movesByTransaction
      .get(id)
      ?.find((m) => m.sleeper_player_id === input.sleeperPlayerId && m.action === action) ?? null;

  const sleeperTrades = input.transactions
    .filter((t) => t.kind === "trade")
    .map((t) => ({
      id: t.id,
      occurredAt: Date.parse(t.occurred_at),
      memberIds: t.team_ids
        .map((teamId) => input.memberIdByTeamId.get(teamId))
        .filter((id): id is number => id !== undefined),
    }))
    .filter((t) => Number.isFinite(t.occurredAt));

  const inSeason = input.registered.filter(
    (trade) => trade.season === input.season && namesPlayer(trade, input.sleeperPlayerId),
  );
  const matched = matchRegisteredTrades(sleeperTrades, inSeason);
  const matchedKeys = new Set([...matched.values()].map((trade) => trade.key));

  for (const t of input.transactions) {
    const added = mine(t.id, "add");
    const dropped = mine(t.id, "drop");
    if (added === null && dropped === null) continue;
    const key = `tx:${t.id}`;
    if (t.kind === "trade") {
      const others = new Map<string, OtherPlayerMove>();
      for (const move of movesByTransaction.get(t.id) ?? []) {
        if (move.sleeper_player_id === input.sleeperPlayerId) continue;
        const other = others.get(move.sleeper_player_id) ?? {
          sleeperPlayerId: move.sleeper_player_id,
          fromTeamId: null,
          toTeamId: null,
        };
        if (move.action === "add") other.toTeamId = move.team_id;
        else other.fromTeamId = move.team_id;
        others.set(move.sleeper_player_id, other);
      }
      const registeredTrade = matched.get(t.id);
      entries.push({
        kind: "traded",
        key,
        at: t.occurred_at,
        week: t.week,
        fromTeamId: dropped?.team_id ?? null,
        toTeamId: added?.team_id ?? null,
        others: [...others.values()],
        faab: faabMoves(t.faab_moves),
        registered: registeredTrade === undefined ? null : link(registeredTrade),
      });
    } else if (t.kind === "waiver") {
      if (added !== null) {
        entries.push({ kind: "claimed", key, at: t.occurred_at, week: t.week, teamId: added.team_id, bid: t.waiver_bid });
      } else if (dropped !== null) {
        entries.push({ kind: "dropped", key, at: t.occurred_at, week: t.week, teamId: dropped.team_id });
      }
    } else if (t.kind === "free_agent") {
      if (added !== null) {
        entries.push({ kind: "added", key, at: t.occurred_at, week: t.week, teamId: added.team_id });
      } else if (dropped !== null) {
        entries.push({ kind: "dropped", key, at: t.occurred_at, week: t.week, teamId: dropped.team_id });
      }
    } else {
      const move = added ?? dropped;
      if (move !== null) {
        entries.push({
          kind: "commissioner",
          key,
          at: t.occurred_at,
          week: t.week,
          teamId: move.team_id,
          action: added !== null ? "add" : "drop",
        });
      }
    }
  }

  for (const trade of inSeason) {
    if (matchedKeys.has(trade.key) || trade.registeredAt === null) continue;
    entries.push({
      kind: "announced",
      key: `reg:${trade.key}`,
      at: trade.registeredAt,
      week: trade.week,
      registered: link(trade),
    });
  }

  return entries.sort((a, b) => {
    if (a.kind === "drafted" && b.kind !== "drafted") return -1;
    if (b.kind === "drafted" && a.kind !== "drafted") return 1;
    return (Date.parse(a.at) || 0) - (Date.parse(b.at) || 0) || a.key.localeCompare(b.key);
  });
}
```

- [ ] **Step 4: Run the tests**

Run: `pnpm --filter @ultimate-guillotine/web exec vitest run src/player/derive/journey.test.ts`
Expected: PASS. If the "orders entries by time" case disagrees on `tx:1`/`tx:2` order, the `occurred_at` values in the fixture decide it — they are a week apart.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/player/derive/journey.ts apps/web/src/player/derive/journey.test.ts
git commit -m "feat(web): a player's season journey, with the league's announcements matched in"
```

---

### Task 6: The card's view, hook, and dialog

**Files:**
- Create: `apps/web/src/player/derive/card.ts` (+ `.test.ts`)
- Create: `apps/web/src/player/usePlayerCard.ts`
- Create: `apps/web/src/player/components/PlayerCard.tsx` (+ `.test.tsx`)

**Interfaces:**
- Produces: `PlayerCardView`, `buildPlayerCardView(input) -> PlayerCardView`; `usePlayerCard({ seasonId, season, sleeperPlayerId, otherPlayerIds }) -> PlayerCardData`; `PlayerCard({ sleeperPlayerId, board, onClose })`, `PlayerCardContent({ view, isPending, errors, onRetry })`, `PLAYER_LOADING_LABEL`, `UNDRAFTED_LABEL`, `NOT_ROSTERED_LABEL`.

- [ ] **Step 1: Write the failing view tests**

`apps/web/src/player/derive/card.test.ts`:

```ts
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
  draft: { teamId: 11, amount: 53, pickNo: 1, round: 1, position: "WR", draftedAt: "2026-09-07T23:01:30.433Z" },
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
  roster: [],
  ...over,
});

const input = (over: Partial<PlayerCardInput> = {}): PlayerCardInput => ({
  sleeperPlayerId: "9493",
  season: 2026,
  teams: [team({ teamId: 11, ownerName: "Ray Regime", roster: [player()] }), team({ teamId: 3 })],
  draftPicks: [
    { team_id: 11, sleeper_player_id: "9493", pick_no: 1, round: 1, position: "WR", amount: 53, drafted_at: "2026-09-07T23:01:30.433Z" },
    { team_id: 3, sleeper_player_id: "4046", pick_no: 2, round: 1, position: "QB", amount: 45, drafted_at: "2026-09-07T23:01:30.433Z" },
    { team_id: 3, sleeper_player_id: "1111", pick_no: 3, round: 1, position: "WR", amount: 31, drafted_at: "2026-09-07T23:01:30.433Z" },
  ],
  memberIdByTeamId: new Map([[11, 1], [3, 2]]),
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
    expect(view.numbers).toEqual({ rostered: true, projected: 14.1, live: 7.8, season: { total: 7.8, weeks: 1 } });
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
        directory: { sleeper_player_id: "9493", full_name: "Puka Nacua", position: "WR", team: "LAR", injury_status: null },
      }),
    );
    expect(view.name).toBe("Puka Nacua");
    expect(view.numbers).toEqual({ rostered: false, season: { total: 7.8, weeks: 1 } });
    expect(view.draft?.stillHere).toBe(false);
  });

  it("labels every team the journey names, and every other player it names", () => {
    const view = buildPlayerCardView(input({ otherPlayers: [{ sleeper_player_id: "12534", full_name: "Brock Bowers", position: "TE", team: "LV", injury_status: null }] }));
    expect(view.ownerLabelByTeamId.get(11)).toBe("Ray Regime");
    expect(view.playerNameById.get("12534")).toBe("Brock Bowers");
  });

  it("names an unknown player and an unknown team honestly", () => {
    const view = buildPlayerCardView(input({ teams: [] , directory: null }));
    expect(view.name).toBe("Unknown player 9493");
    expect(view.ownerLabelByTeamId.get(99)).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm --filter @ultimate-guillotine/web exec vitest run src/player/derive/card.test.ts`
Expected: fails to resolve `./card`.

- [ ] **Step 3: Write the view builder**

`apps/web/src/player/derive/card.ts`:

```ts
import { auctionContext, auctionContextLine, indexDraftPicks } from "@/board/derive/draft";
import type { DraftPickRow, PlayerRow } from "@/board/fetchers";
import type { BoardTeam, RosterPlayer } from "@/board/types";
import type { CatalogTrade } from "@/history/types";

import type { SeasonScoreRow, TransactionMoveRow, TransactionRow } from "../fetchers";
import { buildJourney, type JourneyEntry } from "./journey";
import { seasonPoints, type SeasonPoints } from "./points";

export interface PlayerCardInput {
  sleeperPlayerId: string;
  season: number;
  teams: BoardTeam[];
  draftPicks: DraftPickRow[];
  memberIdByTeamId: ReadonlyMap<number, number>;
  /** The directory row, for a player no roster on the board holds. */
  directory: PlayerRow | null;
  /** Directory rows for the other players the journey names. */
  otherPlayers: PlayerRow[];
  transactions: TransactionRow[];
  moves: TransactionMoveRow[];
  seasonScores: SeasonScoreRow[];
  registered: CatalogTrade[];
}

export type CardNumbers =
  | { rostered: true; projected: number | null; live: number | null; season: SeasonPoints }
  | { rostered: false; season: SeasonPoints };

export interface CardDraft {
  amount: number;
  pickNo: number;
  ownerName: string;
  contextLine: string;
  /** True when the team that drafted him is the one holding him now. */
  stillHere: boolean;
}

/** Everything the card renders, computed once from the board and the three lazy reads. */
export interface PlayerCardView {
  name: string;
  position: string | null;
  nflTeam: string | null;
  injuryStatus: string | null;
  numbers: CardNumbers;
  /** null reads as undrafted. */
  draft: CardDraft | null;
  journey: JourneyEntry[];
  ownerLabelByTeamId: ReadonlyMap<number, string>;
  playerNameById: ReadonlyMap<string, string>;
}

/** The roster row on the board holding this player, with its team, or null. */
function holder(
  teams: readonly BoardTeam[],
  sleeperPlayerId: string,
): { team: BoardTeam; player: RosterPlayer } | null {
  for (const team of teams) {
    const player = team.roster.find((p) => p.sleeperPlayerId === sleeperPlayerId);
    if (player !== undefined) return { team, player };
  }
  return null;
}

export function buildPlayerCardView(input: PlayerCardInput): PlayerCardView {
  const held = holder(input.teams, input.sleeperPlayerId);
  const ownerLabelByTeamId = new Map(input.teams.map((team) => [team.teamId, team.ownerName]));
  const playerNameById = new Map(input.otherPlayers.map((row) => [row.sleeper_player_id, row.full_name]));
  const picks = indexDraftPicks(input.draftPicks);
  const pick = picks.get(input.sleeperPlayerId) ?? null;
  const season = seasonPoints(input.seasonScores, input.sleeperPlayerId);

  const name =
    held?.player.fullName ?? input.directory?.full_name ?? `Unknown player ${input.sleeperPlayerId}`;

  return {
    name,
    position: held?.player.position ?? input.directory?.position ?? null,
    nflTeam: held?.player.nflTeam ?? input.directory?.team ?? null,
    injuryStatus: held?.player.injuryStatus ?? input.directory?.injury_status ?? null,
    numbers:
      held === null
        ? { rostered: false, season }
        : { rostered: true, projected: held.player.projectedPoints, live: held.player.livePoints, season },
    draft:
      pick === null
        ? null
        : {
            amount: pick.amount,
            pickNo: pick.pickNo,
            ownerName: ownerLabelByTeamId.get(pick.teamId) ?? "Unknown owner",
            contextLine: auctionContextLine(auctionContext(pick, picks.values())),
            stillHere: held !== null && held.team.teamId === pick.teamId,
          },
    journey: buildJourney({
      sleeperPlayerId: input.sleeperPlayerId,
      season: input.season,
      pick,
      transactions: input.transactions,
      moves: input.moves,
      registered: input.registered,
      memberIdByTeamId: input.memberIdByTeamId,
    }),
    ownerLabelByTeamId,
    playerNameById,
  };
}
```

- [ ] **Step 4: Run the view tests**

Run: `pnpm --filter @ultimate-guillotine/web exec vitest run src/player/derive/card.test.ts`
Expected: PASS (WR average: (53 + 31) / 2 = 42).

- [ ] **Step 5: The hook**

`apps/web/src/player/usePlayerCard.ts`:

```ts
import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { boardClient } from "@/board/boardClient";
import { fetchPlayers, type PlayerRow } from "@/board/fetchers";
import type { BoardQueryError } from "@/board/useBoardData";
import type { CatalogTrade } from "@/history/types";
import { useTradeCatalog } from "@/history/useTradeCatalog";

import { fetchPlayerTransactions, fetchSeasonScores, type SeasonScoreRow, type TransactionMoveRow, type TransactionRow } from "./fetchers";
import { playerKeys } from "./queryKeys";

export interface PlayerCardData {
  transactions: TransactionRow[];
  moves: TransactionMoveRow[];
  seasonScores: SeasonScoreRow[];
  directory: PlayerRow | null;
  otherPlayers: PlayerRow[];
  registered: CatalogTrade[];
  isPending: boolean;
  errors: BoardQueryError[];
  refetch: () => void;
}

/** Ten seconds: a card is open for a moment, and a second open inside it should not refetch. */
const CARD_STALE_MS = 10_000;

/**
 * The card's reads: the player's transactions (then the other players they name), the season's
 * weekly scores, the directory row for a player the board does not hold, and the trades page's
 * registered trades. Mounted only while a card is open, so the trades hook runs only then.
 */
export function usePlayerCard(input: {
  seasonId: number | null;
  sleeperPlayerId: string;
}): PlayerCardData {
  const queryClient = useQueryClient();
  const enabled = input.seasonId !== null;
  const seasonId = input.seasonId ?? 0;

  const transactions = useQuery({
    queryKey: playerKeys.transactions(seasonId, input.sleeperPlayerId),
    queryFn: () => fetchPlayerTransactions(boardClient, seasonId, input.sleeperPlayerId),
    enabled,
    staleTime: CARD_STALE_MS,
  });
  const scores = useQuery({
    queryKey: playerKeys.seasonScores(seasonId),
    queryFn: () => fetchSeasonScores(boardClient, seasonId),
    enabled,
    staleTime: CARD_STALE_MS,
  });
  const directory = useQuery({
    queryKey: playerKeys.directory([input.sleeperPlayerId]),
    queryFn: () => fetchPlayers(boardClient, [input.sleeperPlayerId]),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const otherIds = useMemo(() => {
    const ids = new Set<string>();
    for (const move of transactions.data?.moves ?? []) {
      if (move.sleeper_player_id !== input.sleeperPlayerId) ids.add(move.sleeper_player_id);
    }
    return [...ids].sort();
  }, [transactions.data, input.sleeperPlayerId]);
  const others = useQuery({
    queryKey: playerKeys.directory(otherIds),
    queryFn: () => fetchPlayers(boardClient, otherIds),
    enabled: otherIds.length > 0,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const catalog = useTradeCatalog();

  const sections: [string, { error: Error | null }][] = [
    ["Transactions", transactions],
    ["Season scores", scores],
    ["Player", directory],
    ["Other players", others],
  ];
  const errors: BoardQueryError[] = [
    ...sections
      .filter(([, query]) => query.error !== null)
      .map(([section, query]) => ({ section, message: query.error?.message ?? "Unknown error" })),
    ...catalog.errors.map((entry) => ({ section: entry.source, message: entry.error.message })),
  ];

  return {
    transactions: transactions.data?.transactions ?? [],
    moves: transactions.data?.moves ?? [],
    seasonScores: scores.data ?? [],
    directory: directory.data?.[0] ?? null,
    otherPlayers: others.data ?? [],
    registered: catalog.trades,
    // isLoading, not isPending: a disabled query stays pending forever (see useBoardData).
    isPending: transactions.isLoading || scores.isLoading || directory.isLoading || others.isLoading || catalog.isPending,
    errors,
    refetch: () => {
      void queryClient.invalidateQueries({ queryKey: playerKeys.all });
      void queryClient.invalidateQueries({ queryKey: ["history"] });
    },
  };
}
```

- [ ] **Step 6: Write the failing component tests**

`apps/web/src/player/components/PlayerCard.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { PlayerCardView } from "../derive/card";
import { NOT_ROSTERED_LABEL, PLAYER_LOADING_LABEL, PlayerCardContent, UNDRAFTED_LABEL } from "./PlayerCard";

const view = (over: Partial<PlayerCardView> = {}): PlayerCardView => ({
  name: "Puka Nacua",
  position: "WR",
  nflTeam: "LAR",
  injuryStatus: null,
  numbers: { rostered: true, projected: 14.1, live: 7.8, season: { total: 19.9, weeks: 3 } },
  draft: { amount: 53, pickNo: 1, ownerName: "Ray Regime", contextLine: "9th priciest pick · 4th WR · WR average $22", stillHere: true },
  journey: [
    { kind: "drafted", key: "draft", at: "2026-09-07T23:01:30Z", week: null, teamId: 11, amount: 53, pickNo: 1 },
    {
      kind: "traded",
      key: "tx:5",
      at: "2026-09-08T14:01:40Z",
      week: 1,
      fromTeamId: 11,
      toTeamId: 16,
      others: [{ sleeperPlayerId: "12534", fromTeamId: 16, toTeamId: 11 }],
      faab: [{ amount: 65, fromTeamId: 11, toTeamId: 16 }],
      registered: { key: "r1", tradeCode: "T-2026-003", announcement: "Puka for Bowers plus 65", rescinded: false },
    },
    { kind: "claimed", key: "tx:9", at: "2026-09-23T00:00:00Z", week: 3, teamId: 3, bid: 12 },
  ],
  ownerLabelByTeamId: new Map([[11, "Ray Regime"], [16, "Rick Vice"], [3, "chobes"]]),
  playerNameById: new Map([["12534", "Brock Bowers"]]),
  ...over,
});

const renderContent = (over: Partial<PlayerCardView> = {}, state: { isPending?: boolean; errors?: { section: string; message: string }[] } = {}) =>
  render(
    <PlayerCardContent
      view={view(over)}
      isPending={state.isPending ?? false}
      errors={state.errors ?? []}
      onRetry={vi.fn()}
    />,
  );

describe("PlayerCardContent", () => {
  it("leads with the name and the position line", () => {
    renderContent();
    expect(screen.getByRole("heading", { name: "Puka Nacua" })).toBeInTheDocument();
    expect(screen.getByText("WR · LAR")).toBeInTheDocument();
  });

  it("shows the numbers with the rostered-weeks caption", () => {
    renderContent();
    expect(screen.getByText("14.1")).toBeInTheDocument();
    expect(screen.getByText("7.8")).toBeInTheDocument();
    expect(screen.getByText("19.9")).toBeInTheDocument();
    expect(screen.getByText("in 3 rostered weeks")).toBeInTheDocument();
  });

  it("shows the draft, the drafter, and the context line", () => {
    renderContent();
    expect(screen.getByText("$53 · pick 1 · Ray Regime")).toBeInTheDocument();
    expect(screen.getByText("9th priciest pick · 4th WR · WR average $22")).toBeInTheDocument();
  });

  it("reads Undrafted with no context line for an undrafted pickup", () => {
    renderContent({ draft: null });
    expect(screen.getByText(UNDRAFTED_LABEL)).toBeInTheDocument();
    expect(screen.queryByText(/priciest/)).not.toBeInTheDocument();
  });

  it("says the player is not rostered this week when no team holds him", () => {
    renderContent({ numbers: { rostered: false, season: { total: 0, weeks: 0 } } });
    expect(screen.getByText(NOT_ROSTERED_LABEL)).toBeInTheDocument();
  });

  it("tells the journey oldest first, naming owners, the other players, the FAAB and the announcement", () => {
    renderContent();
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Drafted by Ray Regime for $53");
    expect(items[1]).toHaveTextContent("Traded from Ray Regime to Rick Vice");
    expect(items[1]).toHaveTextContent("Brock Bowers to Ray Regime");
    expect(items[1]).toHaveTextContent("$65 FAAB from Ray Regime to Rick Vice");
    expect(items[1]).toHaveTextContent("T-2026-003");
    expect(items[1]).toHaveTextContent("Puka for Bowers plus 65");
    expect(items[2]).toHaveTextContent("Claimed by chobes for a $12 bid");
  });

  it("shows the loading sentence while the reads are on their way", () => {
    renderContent({}, { isPending: true });
    expect(screen.getByRole("status", { name: PLAYER_LOADING_LABEL })).toBeInTheDocument();
  });

  it("names a failed section with a retry, and keeps the rest", () => {
    renderContent({}, { errors: [{ section: "Transactions", message: "network down" }] });
    expect(screen.getByText("Transactions could not load")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Puka Nacua" })).toBeInTheDocument();
  });

  it("strikes through a rescinded announcement", () => {
    renderContent({
      journey: [
        { kind: "announced", key: "reg:r2", at: "2026-09-10T00:00:00Z", week: 1, registered: { key: "r2", tradeCode: "T-2026-004", announcement: "Undo that", rescinded: true } },
      ],
    });
    expect(screen.getByRole("listitem")).toHaveAttribute("data-rescinded", "true");
    fireEvent.click(screen.getByText("T-2026-004"));
  });
});
```

- [ ] **Step 7: Run them to verify they fail**

Run: `pnpm --filter @ultimate-guillotine/web exec vitest run src/player/components/PlayerCard.test.tsx`
Expected: fails to resolve `./PlayerCard`.

- [ ] **Step 8: Write the components**

`apps/web/src/player/components/PlayerCard.tsx`:

```tsx
import { injuryTag } from "@/board/derive/availability";
import type { DraftPickRow } from "@/board/fetchers";
import type { BoardTeam } from "@/board/types";
import type { BoardQueryError } from "@/board/useBoardData";
import { ExplainedBadge } from "@/components/explained-badge";
import { LoadingState } from "@/components/loading-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { badgeVariants } from "@/components/ui/badge-variants";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

import { buildPlayerCardView, type PlayerCardView } from "../derive/card";
import { formatDateLine } from "../derive/dateLine";
import type { JourneyEntry } from "../derive/journey";
import { rosteredWeeksCaption } from "../derive/points";
import { usePlayerCard } from "../usePlayerCard";

export const PLAYER_LOADING_LABEL = "Loading the player";
export const UNDRAFTED_LABEL = "Undrafted";
export const NOT_ROSTERED_LABEL = "Not rostered this week";
const NO_NUMBER_TEXT = "—";
const DECIMALS = 1;
const UNKNOWN_OWNER = "Unknown owner";
const TRADE_CODE_DESCRIPTION = "The Registrar's code for this trade, as it was recorded from the league chat";
const RESCINDED_DESCRIPTION = "The league undid this trade after it was recorded; it is kept for the record";

function figure(value: number | null): string {
  return value === null ? NO_NUMBER_TEXT : value.toFixed(DECIMALS);
}

function Figure({ label, value, caption }: { label: string; value: string; caption?: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-2xl leading-none figures text-foreground">{value}</p>
      {caption === undefined ? null : <p className="mt-1 text-xs text-muted-foreground">{caption}</p>}
    </div>
  );
}

function Registered({ link }: { link: NonNullable<Extract<JourneyEntry, { kind: "traded" }>["registered"]> }) {
  return (
    <div className="mt-1 space-y-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <ExplainedBadge description={TRADE_CODE_DESCRIPTION} className={badgeVariants({ variant: "default" })}>
          {link.tradeCode}
        </ExplainedBadge>
        {link.rescinded ? (
          <ExplainedBadge description={RESCINDED_DESCRIPTION} className={badgeVariants({ variant: "destructive" })}>
            Rescinded
          </ExplainedBadge>
        ) : null}
      </div>
      {link.announcement === null ? null : (
        <blockquote className="line-clamp-4 border-l-2 pl-2 text-xs whitespace-pre-line text-muted-foreground">
          {link.announcement}
        </blockquote>
      )}
    </div>
  );
}

/** One journey entry in words. Owners by the board's label; players by the directory. */
function JourneyItem({ entry, view }: { entry: JourneyEntry; view: PlayerCardView }) {
  const owner = (teamId: number | null) =>
    teamId === null ? UNKNOWN_OWNER : (view.ownerLabelByTeamId.get(teamId) ?? UNKNOWN_OWNER);
  const playerName = (id: string) => view.playerNameById.get(id) ?? `Unknown player ${id}`;
  const rescinded = (entry.kind === "traded" && entry.registered?.rescinded === true) || (entry.kind === "announced" && entry.registered.rescinded);
  let sentence: string;
  switch (entry.kind) {
    case "drafted":
      sentence = `Drafted by ${owner(entry.teamId)} for $${entry.amount}`;
      break;
    case "traded":
      sentence = `Traded from ${owner(entry.fromTeamId)} to ${owner(entry.toTeamId)}`;
      break;
    case "dropped":
      sentence = `Dropped by ${owner(entry.teamId)}`;
      break;
    case "claimed":
      sentence = entry.bid === null ? `Claimed by ${owner(entry.teamId)}` : `Claimed by ${owner(entry.teamId)} for a $${entry.bid} bid`;
      break;
    case "added":
      sentence = `Added by ${owner(entry.teamId)}`;
      break;
    case "commissioner":
      sentence = entry.action === "add" ? `Commissioner move to ${owner(entry.teamId)}` : `Commissioner move from ${owner(entry.teamId)}`;
      break;
    case "announced":
      sentence = "Announced";
      break;
  }
  return (
    <li data-journey={entry.kind} data-rescinded={rescinded || undefined} className="text-sm">
      <p className="text-xs text-muted-foreground">{formatDateLine(entry.at, entry.week)}</p>
      <p className={cn("font-medium", rescinded && "line-through")}>{sentence}</p>
      {entry.kind === "traded" && entry.others.length > 0 ? (
        <ul className="text-xs text-muted-foreground">
          {entry.others.map((other) => (
            <li key={other.sleeperPlayerId}>{`${playerName(other.sleeperPlayerId)} to ${owner(other.toTeamId)}`}</li>
          ))}
        </ul>
      ) : null}
      {entry.kind === "traded" && entry.faab.length > 0 ? (
        <ul className="text-xs text-muted-foreground">
          {entry.faab.map((move, index) => (
            <li key={index}>{`$${move.amount} FAAB from ${owner(move.fromTeamId)} to ${owner(move.toTeamId)}`}</li>
          ))}
        </ul>
      ) : null}
      {entry.kind === "traded" && entry.registered !== null ? <Registered link={entry.registered} /> : null}
      {entry.kind === "announced" ? <Registered link={entry.registered} /> : null}
    </li>
  );
}

/** The card's body, given its view: pure, so every state is a fixture in the test. */
export function PlayerCardContent({
  view,
  isPending,
  errors,
  onRetry,
}: {
  view: PlayerCardView;
  isPending: boolean;
  errors: BoardQueryError[];
  onRetry: () => void;
}) {
  const tag = injuryTag(view.injuryStatus);
  const meta = [view.position, view.nflTeam].filter(Boolean).join(" · ");
  return (
    <DialogContent aria-describedby={undefined}>
      <DialogHeader>
        <DialogTitle>{view.name}</DialogTitle>
        <DialogDescription>
          {meta === "" ? null : <span>{meta}</span>}
          {tag === null ? null : (
            <span className={cn("ml-2 rounded border px-1 text-[0.6875rem] font-medium", tag.isUnavailable ? "border-destructive/40 text-destructive" : "border-border")}>
              {tag.title}
            </span>
          )}
        </DialogDescription>
      </DialogHeader>

      <div className="min-h-0 space-y-4 overflow-y-auto">
        {errors.map((error) => (
          <Alert key={error.section} variant="destructive">
            <AlertTitle>{error.section} could not load</AlertTitle>
            <AlertDescription className="flex flex-wrap items-center gap-3">
              <span>{error.message}</span>
              <Button size="sm" variant="outline" onClick={onRetry}>
                Retry
              </Button>
            </AlertDescription>
          </Alert>
        ))}

        <section aria-label="Numbers" className="flex flex-wrap gap-6">
          {view.numbers.rostered ? (
            <>
              <Figure label="Projected" value={figure(view.numbers.projected)} />
              <Figure label="Live" value={figure(view.numbers.live)} />
            </>
          ) : (
            <p className="text-sm text-muted-foreground">{NOT_ROSTERED_LABEL}</p>
          )}
          <Figure
            label="Season"
            value={view.numbers.season.total.toFixed(DECIMALS)}
            caption={rosteredWeeksCaption(view.numbers.season.weeks)}
          />
        </section>

        <section aria-label="Draft">
          <h3 className="text-xs font-medium text-muted-foreground">Draft</h3>
          {view.draft === null ? (
            <p className="mt-1 text-sm">{UNDRAFTED_LABEL}</p>
          ) : (
            <>
              <p className="mt-1 text-sm font-medium">{`$${view.draft.amount} · pick ${view.draft.pickNo} · ${view.draft.ownerName}`}</p>
              <p className="text-xs text-muted-foreground">{view.draft.contextLine}</p>
            </>
          )}
        </section>

        <section aria-label="Journey">
          <h3 className="text-xs font-medium text-muted-foreground">Journey</h3>
          {isPending ? (
            <div className="mt-1">
              <LoadingState label={PLAYER_LOADING_LABEL} />
            </div>
          ) : (
            <ol className="mt-1 space-y-3">
              {view.journey.map((entry) => (
                <JourneyItem key={entry.key} entry={entry} view={view} />
              ))}
            </ol>
          )}
        </section>
      </div>
    </DialogContent>
  );
}

export interface PlayerCardBoard {
  season: number | null;
  seasonId: number | null;
  teams: BoardTeam[];
  draftPicks: DraftPickRow[];
  memberIdByTeamId: ReadonlyMap<number, number>;
}

/**
 * The controlled dialog: open while mounted, and `onClose` when Radix asks to close it. Mounted
 * by the page only while `?player=` names somebody, so the hook inside runs only then.
 */
export function PlayerCard({
  sleeperPlayerId,
  board,
  onClose,
}: {
  sleeperPlayerId: string;
  board: PlayerCardBoard;
  onClose: () => void;
}) {
  const data = usePlayerCard({ seasonId: board.seasonId, sleeperPlayerId });
  const view = buildPlayerCardView({
    sleeperPlayerId,
    season: board.season ?? 0,
    teams: board.teams,
    draftPicks: board.draftPicks,
    memberIdByTeamId: board.memberIdByTeamId,
    directory: data.directory,
    otherPlayers: data.otherPlayers,
    transactions: data.transactions,
    moves: data.moves,
    seasonScores: data.seasonScores,
    registered: data.registered,
  });
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <PlayerCardContent view={view} isPending={data.isPending} errors={data.errors} onRetry={data.refetch} />
    </Dialog>
  );
}
```

`PlayerCardContent` renders `DialogContent`, which needs a `Dialog` root in tests: wrap the test's `render(...)` in `<Dialog open>` — update `renderContent` in the test to `render(<Dialog open><PlayerCardContent … /></Dialog>)`, importing `Dialog` from `@/components/ui/dialog`.

- [ ] **Step 9: Run the component tests and the gates**

Run: `pnpm --filter @ultimate-guillotine/web exec vitest run src/player && pnpm --filter @ultimate-guillotine/web exec tsc --noEmit && pnpm lint`
Expected: PASS. The `line-clamp-4` and `figures` classes exist in the project's Tailwind and `globals.css`.

- [ ] **Step 10: Commit**

```bash
git add apps/web/src/player
git commit -m "feat(web): the player card"
```

---

### Task 7: Open from the URL, close to it

**Files:**
- Modify: `apps/web/src/app/board/BoardPage.tsx`, `apps/web/src/app/board/BoardPage.test.tsx`

**Interfaces:**
- Produces: `PLAYER_PARAM = "player"`; the page mounts `<PlayerCard>` while the param names a player; `onOpenPlayer` pushes the param; close pops the entry it pushed or, for a shared link, replaces the URL without the param.

- [ ] **Step 1: Write the failing page tests**

In `apps/web/src/app/board/BoardPage.test.tsx`, add a hoisted mock beside the others:

```ts
const playerCard = vi.hoisted(() => ({
  current: {
    transactions: [],
    moves: [],
    seasonScores: [],
    directory: null,
    otherPlayers: [],
    registered: [],
    isPending: false,
    errors: [],
    refetch: vi.fn(),
  },
}));

vi.mock("@/player/usePlayerCard", () => ({
  usePlayerCard: () => playerCard.current,
}));
```

And a `describe` at the end:

```tsx
describe("the player card", () => {
  const nacua = player({ sleeperPlayerId: "9493", fullName: "Puka Nacua" });

  it("opens from the URL on load, labelled by the player's name", () => {
    boardData.current = result({ teams: [team({ teamId: 1, roster: [nacua] })] });
    renderPage("/?player=9493");
    expect(screen.getByRole("dialog", { name: "Puka Nacua" })).toBeInTheDocument();
  });

  it("opens when a name is tapped, and writes the player into the URL", () => {
    boardData.current = result({ teams: [team({ teamId: 1, roster: [nacua] })] });
    renderPage("/?sort=faab");
    fireEvent.click(screen.getByRole("button", { name: /Team 1/ }));
    fireEvent.click(screen.getByRole("button", { name: "Puka Nacua" }));
    expect(screen.getByRole("dialog", { name: "Puka Nacua" })).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("/?sort=faab&player=9493");
  });

  it("closes by taking the player out of the URL, keeping the rest", () => {
    boardData.current = result({ teams: [team({ teamId: 1, roster: [nacua] })] });
    renderPage("/?sort=faab&player=9493");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent("/?sort=faab");
  });

  it("still opens for a player the board does not hold", () => {
    boardData.current = result({ teams: [team({ teamId: 1 })] });
    playerCard.current = {
      ...playerCard.current,
      directory: { sleeper_player_id: "9493", full_name: "Puka Nacua", position: "WR", team: "LAR", injury_status: null },
    };
    renderPage("/?player=9493");
    expect(screen.getByRole("dialog", { name: "Puka Nacua" })).toBeInTheDocument();
    expect(screen.getByText("Not rostered this week")).toBeInTheDocument();
  });
});
```

The card-open test clicks the team card's toggle first because roster rows mount only while the card is open; if the toggle's accessible name differs, use the button that contains `owner1`.

- [ ] **Step 2: Run them to verify they fail**

Run: `pnpm --filter @ultimate-guillotine/web exec vitest run src/app/board/BoardPage.test.tsx`
Expected: the four new cases fail — no dialog, no `player` param.

- [ ] **Step 3: Wire the page**

In `apps/web/src/app/board/BoardPage.tsx`: import `useNavigate` from `react-router` and `PlayerCard` from `@/player/components/PlayerCard`. Add `const PLAYER_PARAM = "player";`. Replace the Task 3 `noopOpen` with:

```tsx
  const navigate = useNavigate();
  const openPlayerId = (searchParams.get(PLAYER_PARAM) ?? "").trim() || null;
  /**
   * `setSearchParams` changes identity with the params, and the opener is a prop on every
   * memoized card, so the latest setter rides in a ref and the opener depends on nothing.
   */
  const setSearchParamsRef = useRef(setSearchParams);
  useEffect(() => {
    setSearchParamsRef.current = setSearchParams;
  }, [setSearchParams]);
  /** True when this page pushed the open card's entry, so closing can pop it. */
  const openedHereRef = useRef(false);

  const handleOpenPlayer = useCallback((sleeperPlayerId: string) => {
    openedHereRef.current = true;
    setSearchParamsRef.current((previous) => {
      const next = new URLSearchParams(previous);
      next.set(PLAYER_PARAM, sleeperPlayerId);
      return next;
    });
  }, []);

  const handleClosePlayer = useCallback(() => {
    if (openedHereRef.current) {
      // A tap pushed the entry; the back button and the close button do the same thing.
      openedHereRef.current = false;
      void navigate(-1);
      return;
    }
    // A shared link: there is no entry of ours to pop, so the URL is replaced in place.
    setSearchParamsRef.current(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.delete(PLAYER_PARAM);
        return next;
      },
      { replace: true },
    );
  }, [navigate]);
```

Pass `onOpenPlayer={handleOpenPlayer}` to every `TeamCard` and to `PositionView`. Before the closing `</main>`:

```tsx
      {openPlayerId !== null ? (
        <PlayerCard
          sleeperPlayerId={openPlayerId}
          onClose={handleClosePlayer}
          board={{
            season: board.season,
            seasonId: board.seasonId,
            teams: board.teams,
            draftPicks: board.draftPicks,
            memberIdByTeamId: board.memberIdByTeamId,
          }}
        />
      ) : null}
```

- [ ] **Step 4: Run the page tests and all three gates**

Run: `pnpm --filter @ultimate-guillotine/web exec tsc --noEmit && pnpm test:web && pnpm lint`
Expected: PASS. If the close test's `navigate(-1)` leaves the `MemoryRouter` on the same entry (the card was opened from the initial URL, so `openedHereRef` is false and the replace path runs), the assertion holds; if a test opens by tap and closes, expect the location to return to the pre-open URL.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/app/board
git commit -m "feat(web): a player card opens from ?player= and closes back to the board"
```

---

### Task 8: The draft page

Ben (2026-09-10): "make a draft tab on the site just to show the full draft." A fourth page, `/draft`, in its own chunk like the trades and history pages: the season's auction as one list, sortable by pick order, by price, or grouped by team with each team's spend and what its unspent dollars became in FAAB. Every name links to the board with `?player=<id>`, so the card is one tap away.

**Files:**
- Create: `apps/web/src/draft/derive/rows.ts`, `apps/web/src/draft/derive/rows.test.ts`
- Create: `apps/web/src/draft/useDraftPage.ts`
- Create: `apps/web/src/draft/components/DraftSkeleton.tsx`
- Create: `apps/web/src/app/draft/DraftPage.tsx`, `apps/web/src/app/draft/DraftPage.test.tsx`
- Modify: `apps/web/src/router.tsx`, `apps/web/src/app/lazyPages.ts`, `apps/web/src/app/layout.tsx`

**Interfaces:**
- Consumes: `fetchDraftPicks`, `fetchTeams`, `fetchMembers`, `fetchPlayers`, `fetchSeasonByYear`, `fetchLatestSeason`, `useCurrentSeason`, `resolveOwnerLabel`, `boardKeys`, `fingerprintIds`.
- Produces: `DraftRow`, `DraftSortMode = "pick" | "price" | "team"`, `parseDraftSortMode(raw)`, `draftRows(picks, teams, members, players) -> DraftRow[]`, `sortDraftRows(rows, mode) -> DraftRow[]`, `TeamSpend`, `teamSpend(rows, budgetPerTeam) -> TeamSpend[]`, `DraftSummary`, `draftSummary(rows) -> DraftSummary`, `FAAB_PER_DRAFT_DOLLAR`, `draftBudgetPerTeam(waiverBudget) -> number | null`; `useDraftPage() -> DraftPageData`; `DraftPage`; `DRAFT_LOADING_LABEL`; `NO_DRAFT_LABEL`.

- [ ] **Step 1: Write the failing derive tests**

`apps/web/src/draft/derive/rows.test.ts`:

```ts
/** @vitest-environment node */
import { describe, expect, it } from "vitest";

import {
  draftBudgetPerTeam,
  draftRows,
  draftSummary,
  parseDraftSortMode,
  sortDraftRows,
  teamSpend,
  type DraftRow,
} from "./rows";

const picks = [
  { team_id: 11, sleeper_player_id: "9493", pick_no: 1, round: 1, position: "WR", amount: 53, drafted_at: "2026-09-07T23:01:30Z" },
  { team_id: 3, sleeper_player_id: "4046", pick_no: 2, round: 1, position: "QB", amount: 45, drafted_at: "2026-09-07T23:01:30Z" },
  { team_id: 11, sleeper_player_id: "1111", pick_no: 3, round: 1, position: "RB", amount: 45, drafted_at: "2026-09-07T23:01:30Z" },
  { team_id: 3, sleeper_player_id: "2222", pick_no: 4, round: 1, position: "K", amount: 1, drafted_at: "2026-09-07T23:01:30Z" },
];
const teams = [
  { id: 11, sleeper_roster_id: 1, team_name: "Ray Regime", member_id: 101 },
  { id: 3, sleeper_roster_id: 2, team_name: "chobes", member_id: 103 },
];
const members = [
  { id: 101, sleeper_display_name: "jrayay", nickname: "Jesse" },
  { id: 103, sleeper_display_name: "chobes", nickname: null },
];
const players = [
  { sleeper_player_id: "9493", full_name: "Puka Nacua", position: "WR", team: "LAR", injury_status: null },
  { sleeper_player_id: "4046", full_name: "Patrick Mahomes", position: "QB", team: "KC", injury_status: null },
];

const rows = () => draftRows(picks, teams, members, players);

describe("draftRows", () => {
  it("joins a pick to its name, NFL team, and owner label", () => {
    const [first] = rows();
    expect(first).toEqual({
      sleeperPlayerId: "9493",
      pickNo: 1,
      round: 1,
      amount: 53,
      position: "WR",
      fullName: "Puka Nacua",
      nflTeam: "LAR",
      teamId: 11,
      ownerName: "Jesse",
    });
  });

  it("names a player the directory lacks by his id, and keeps the pick's position", () => {
    const row = rows().find((r) => r.sleeperPlayerId === "1111") as DraftRow;
    expect(row.fullName).toBe("Unknown player 1111");
    expect(row.position).toBe("RB");
    expect(row.nflTeam).toBeNull();
  });

  it("falls back to the Sleeper display name for an owner with no nickname", () => {
    expect(rows().find((r) => r.teamId === 3)?.ownerName).toBe("chobes");
  });
});

describe("sortDraftRows", () => {
  it("is pick order by default", () => {
    expect(sortDraftRows(rows(), "pick").map((r) => r.pickNo)).toEqual([1, 2, 3, 4]);
  });

  it("sorts by price, ties broken by pick order", () => {
    expect(sortDraftRows(rows(), "price").map((r) => r.pickNo)).toEqual([1, 2, 3, 4]);
    expect(sortDraftRows(rows(), "price").map((r) => r.amount)).toEqual([53, 45, 45, 1]);
  });

  it("groups by team in spend order, priciest first within a team, and never mutates its input", () => {
    const input = rows();
    const sorted = sortDraftRows(input, "team");
    expect(sorted.map((r) => `${r.teamId}:${r.amount}`)).toEqual(["11:53", "11:45", "3:45", "3:1"]);
    expect(input.map((r) => r.pickNo)).toEqual([1, 2, 3, 4]);
  });
});

describe("parseDraftSortMode", () => {
  it("reads the three modes and falls back to pick order", () => {
    expect(parseDraftSortMode("price")).toBe("price");
    expect(parseDraftSortMode("team")).toBe("team");
    expect(parseDraftSortMode("nonsense")).toBe("pick");
    expect(parseDraftSortMode(null)).toBe("pick");
  });
});

describe("teamSpend", () => {
  it("totals each team, in spend order, with the unspent dollars as FAAB", () => {
    expect(teamSpend(rows(), 200)).toEqual([
      { teamId: 11, ownerName: "Jesse", picks: 2, spent: 98, unspent: 102, faab: 510 },
      { teamId: 3, ownerName: "chobes", picks: 2, spent: 46, unspent: 154, faab: 770 },
    ]);
  });

  it("carries no unspent figure without a budget", () => {
    expect(teamSpend(rows(), null)[0]).toMatchObject({ spent: 98, unspent: null, faab: null });
  });
});

describe("draftBudgetPerTeam", () => {
  it("is the FAAB budget divided by the league's five-to-one rule", () => {
    expect(draftBudgetPerTeam(1000)).toBe(200);
    expect(draftBudgetPerTeam(null)).toBeNull();
  });
});

describe("draftSummary", () => {
  it("counts the picks, the dollars, and the average to the dollar", () => {
    expect(draftSummary(rows())).toEqual({ pickCount: 4, spent: 144, average: 36 });
    expect(draftSummary([])).toEqual({ pickCount: 0, spent: 0, average: null });
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm --filter @ultimate-guillotine/web exec vitest run src/draft`
Expected: fails to resolve `./rows`.

- [ ] **Step 3: Write the derive module**

`apps/web/src/draft/derive/rows.ts`:

```ts
import { resolveOwnerLabel } from "@/board/derive/join";
import type { DraftPickRow, MemberRow, PlayerRow, TeamRow } from "@/board/fetchers";

export interface DraftRow {
  sleeperPlayerId: string;
  pickNo: number;
  round: number;
  amount: number;
  /** The position Sleeper recorded on the pick, which is what the auction ranked by. */
  position: string | null;
  fullName: string;
  nflTeam: string | null;
  teamId: number;
  ownerName: string;
}

export const DRAFT_SORT_MODES = ["pick", "price", "team"] as const;
export type DraftSortMode = (typeof DRAFT_SORT_MODES)[number];
export const DEFAULT_DRAFT_SORT_MODE: DraftSortMode = "pick";
export const DRAFT_SORT_LABELS: Record<DraftSortMode, string> = {
  pick: "Pick order",
  price: "Price",
  team: "By team",
};

export function parseDraftSortMode(raw: string | null | undefined): DraftSortMode {
  return DRAFT_SORT_MODES.includes(raw as DraftSortMode)
    ? (raw as DraftSortMode)
    : DEFAULT_DRAFT_SORT_MODE;
}

/**
 * The league's rule (docs/rules): every unspent auction dollar becomes five FAAB dollars, so the
 * auction budget is the FAAB budget over five. `seasons.waiver_budget` is the only budget the
 * data layer stores.
 */
export const FAAB_PER_DRAFT_DOLLAR = 5;

export function draftBudgetPerTeam(waiverBudget: number | null): number | null {
  return waiverBudget === null ? null : Math.round(waiverBudget / FAAB_PER_DRAFT_DOLLAR);
}

/** Every pick joined to a name, an NFL team and an owner label, in pick order. */
export function draftRows(
  picks: readonly DraftPickRow[],
  teams: readonly TeamRow[],
  members: readonly MemberRow[],
  players: readonly PlayerRow[],
): DraftRow[] {
  const memberById = new Map(members.map((m) => [m.id, m]));
  const teamById = new Map(teams.map((t) => [t.id, t]));
  const playerById = new Map(players.map((p) => [p.sleeper_player_id, p]));
  return [...picks]
    .sort((a, b) => a.pick_no - b.pick_no)
    .map((pick) => {
      const team = teamById.get(pick.team_id);
      const player = playerById.get(pick.sleeper_player_id);
      return {
        sleeperPlayerId: pick.sleeper_player_id,
        pickNo: pick.pick_no,
        round: pick.round,
        amount: pick.amount,
        position: pick.position ?? player?.position ?? null,
        fullName: player?.full_name ?? `Unknown player ${pick.sleeper_player_id}`,
        nflTeam: player?.team ?? null,
        teamId: pick.team_id,
        ownerName: resolveOwnerLabel(
          team === undefined ? undefined : memberById.get(team.member_id),
        ),
      };
    });
}

export interface TeamSpend {
  teamId: number;
  ownerName: string;
  picks: number;
  spent: number;
  /** null when the budget is unknown. */
  unspent: number | null;
  /** What the unspent dollars became, by `FAAB_PER_DRAFT_DOLLAR`; null with `unspent`. */
  faab: number | null;
}

/** Each team's auction, in spend order, then owner label. */
export function teamSpend(rows: readonly DraftRow[], budgetPerTeam: number | null): TeamSpend[] {
  const byTeam = new Map<number, TeamSpend>();
  for (const row of rows) {
    const entry = byTeam.get(row.teamId) ?? {
      teamId: row.teamId,
      ownerName: row.ownerName,
      picks: 0,
      spent: 0,
      unspent: null,
      faab: null,
    };
    entry.picks += 1;
    entry.spent += row.amount;
    byTeam.set(row.teamId, entry);
  }
  const spends = [...byTeam.values()].map((entry) => {
    if (budgetPerTeam === null) return entry;
    const unspent = Math.max(0, budgetPerTeam - entry.spent);
    return { ...entry, unspent, faab: unspent * FAAB_PER_DRAFT_DOLLAR };
  });
  return spends.sort(
    (a, b) => b.spent - a.spent || a.ownerName.localeCompare(b.ownerName) || a.teamId - b.teamId,
  );
}

/** Sorts a copy: pick order, price descending (ties by pick), or grouped by team in spend order. */
export function sortDraftRows(rows: readonly DraftRow[], mode: DraftSortMode): DraftRow[] {
  const copy = [...rows];
  if (mode === "price") {
    return copy.sort((a, b) => b.amount - a.amount || a.pickNo - b.pickNo);
  }
  if (mode === "team") {
    const order = new Map(teamSpend(rows, null).map((spend, index) => [spend.teamId, index]));
    return copy.sort(
      (a, b) =>
        (order.get(a.teamId) ?? 0) - (order.get(b.teamId) ?? 0) ||
        b.amount - a.amount ||
        a.pickNo - b.pickNo,
    );
  }
  return copy.sort((a, b) => a.pickNo - b.pickNo);
}

export interface DraftSummary {
  pickCount: number;
  spent: number;
  /** The mean price to the dollar, or null with no picks. */
  average: number | null;
}

export function draftSummary(rows: readonly DraftRow[]): DraftSummary {
  const spent = rows.reduce((sum, row) => sum + row.amount, 0);
  return {
    pickCount: rows.length,
    spent,
    average: rows.length === 0 ? null : Math.round(spent / rows.length),
  };
}
```

- [ ] **Step 4: Run the derive tests**

Run: `pnpm --filter @ultimate-guillotine/web exec vitest run src/draft`
Expected: PASS.

- [ ] **Step 5: The page's hook and skeleton**

`apps/web/src/draft/useDraftPage.ts`:

```ts
import { useMemo } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";

import { boardClient } from "@/board/boardClient";
import {
  fetchDraftPicks,
  fetchLatestSeason,
  fetchMembers,
  fetchPlayers,
  fetchSeasonByYear,
  fetchTeams,
  type DraftPickRow,
  type MemberRow,
  type PlayerRow,
  type TeamRow,
} from "@/board/fetchers";
import { boardKeys, fingerprintIds } from "@/board/queryKeys";
import type { BoardQueryError } from "@/board/useBoardData";
import { useCurrentSeason } from "@/history/useCurrentSeason";

export interface DraftPageData {
  season: number | null;
  /** `seasons.waiver_budget`, for the auction budget the unspent figures derive from. */
  waiverBudget: number | null;
  picks: DraftPickRow[];
  teams: TeamRow[];
  members: MemberRow[];
  players: PlayerRow[];
  isPending: boolean;
  errors: BoardQueryError[];
  refetchAll: () => void;
}

/** The auction is a fact; the directory is a lookup. Neither goes stale on a timer. */
const STATIC = { staleTime: Number.POSITIVE_INFINITY, refetchInterval: false as const };

/**
 * The season the same way the board resolves it — `nfl_state`'s year, or the newest row in the
 * offseason — then the picks, the teams and members behind the owner labels, and the names.
 * Every key is the board's, so a visitor coming from the board pays for nothing twice.
 */
export function useDraftPage(): DraftPageData {
  const queryClient = useQueryClient();
  const current = useCurrentSeason();
  const seasonRow = useQuery({
    queryKey: boardKeys.season(current.season ?? 0),
    queryFn: () => fetchSeasonByYear(boardClient, current.season as number),
    enabled: current.season !== null,
    ...STATIC,
  });
  const latestSeason = useQuery({
    queryKey: boardKeys.latestSeason(),
    queryFn: () => fetchLatestSeason(boardClient),
    enabled: seasonRow.isSuccess && seasonRow.data === null,
    ...STATIC,
  });
  const resolved = seasonRow.data ?? latestSeason.data ?? null;
  const seasonId = resolved?.id ?? null;
  const hasSeason = seasonId !== null;

  const picks = useQuery({
    queryKey: boardKeys.draftPicks(seasonId ?? 0),
    queryFn: () => fetchDraftPicks(boardClient, seasonId as number),
    enabled: hasSeason,
    ...STATIC,
  });
  const teams = useQuery({
    queryKey: boardKeys.teams(seasonId ?? 0),
    queryFn: () => fetchTeams(boardClient, seasonId as number),
    enabled: hasSeason,
    ...STATIC,
  });
  const members = useQuery({
    queryKey: boardKeys.members(),
    queryFn: () => fetchMembers(boardClient),
    ...STATIC,
  });
  const ids = useMemo(
    () => [...new Set((picks.data ?? []).map((pick) => pick.sleeper_player_id))].sort(),
    [picks.data],
  );
  const fingerprint = useMemo(() => fingerprintIds(ids), [ids]);
  const players = useQuery({
    queryKey: boardKeys.players(seasonId ?? 0, fingerprint),
    queryFn: () => fetchPlayers(boardClient, ids),
    enabled: hasSeason && ids.length > 0,
    placeholderData: keepPreviousData,
    ...STATIC,
  });

  const sections: [string, { error: Error | null }][] = [
    ["Season", seasonRow],
    ["Season", latestSeason],
    ["Draft", picks],
    ["Teams", teams],
    ["Owners", members],
    ["Players", players],
  ];
  const errors: BoardQueryError[] = sections
    .filter(([, query]) => query.error !== null)
    .map(([section, query]) => ({ section, message: query.error?.message ?? "Unknown error" }));

  return {
    season: resolved?.year ?? null,
    waiverBudget: resolved?.waiver_budget ?? null,
    picks: picks.data ?? [],
    teams: teams.data ?? [],
    members: members.data ?? [],
    players: players.data ?? [],
    // isLoading, not isPending: a disabled query stays pending forever (see useBoardData).
    isPending:
      current.isPending ||
      seasonRow.isLoading ||
      latestSeason.isLoading ||
      picks.isLoading ||
      teams.isLoading ||
      members.isLoading ||
      players.isLoading,
    errors,
    refetchAll: () => {
      void queryClient.invalidateQueries({ queryKey: boardKeys.all });
    },
  };
}
```

`apps/web/src/draft/components/DraftSkeleton.tsx`:

```tsx
import { LoadingState } from "@/components/loading-state";
import { Skeleton } from "@/components/ui/skeleton";
import { REVEAL_CLASS, revealStyle } from "@/motion/reveal";

export const DRAFT_LOADING_LABEL = "Loading the draft";

const PLACEHOLDER_ROW_COUNT = 9;

/** The list's stand-in: the sentence, then row-shaped blocks hidden from assistive technology. */
export function DraftListSkeleton({ revealIndex = 0 }: { revealIndex?: number }) {
  return (
    <div className="space-y-2">
      <LoadingState label={DRAFT_LOADING_LABEL} />
      <ul aria-hidden="true" className="space-y-1">
        {Array.from({ length: PLACEHOLDER_ROW_COUNT }, (_, index) => (
          <li key={index} className={REVEAL_CLASS} style={revealStyle(revealIndex + 1 + index)}>
            <Skeleton className="h-10 w-full rounded-md" />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The whole page's stand-in while its chunk is on its way (`app/layout.tsx`). */
export function DraftPageSkeleton() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-20 w-full rounded-xl" />
      <DraftListSkeleton revealIndex={0} />
    </div>
  );
}
```

- [ ] **Step 6: Write the failing page test**

`apps/web/src/app/draft/DraftPage.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DRAFT_LOADING_LABEL } from "@/draft/components/DraftSkeleton";
import type { DraftPageData } from "@/draft/useDraftPage";

import { DraftPage, NO_DRAFT_LABEL } from "./DraftPage";

const data = vi.hoisted(() => ({ current: null as DraftPageData | null }));

vi.mock("@/draft/useDraftPage", () => ({
  useDraftPage: () => data.current,
}));

const result = (over: Partial<DraftPageData> = {}): DraftPageData => ({
  season: 2026,
  waiverBudget: 1000,
  picks: [
    { team_id: 11, sleeper_player_id: "9493", pick_no: 1, round: 1, position: "WR", amount: 53, drafted_at: "2026-09-07T23:01:30Z" },
    { team_id: 3, sleeper_player_id: "4046", pick_no: 2, round: 1, position: "QB", amount: 45, drafted_at: "2026-09-07T23:01:30Z" },
    { team_id: 11, sleeper_player_id: "1111", pick_no: 3, round: 1, position: "RB", amount: 60, drafted_at: "2026-09-07T23:01:30Z" },
  ],
  teams: [
    { id: 11, sleeper_roster_id: 1, team_name: "Ray Regime", member_id: 101 },
    { id: 3, sleeper_roster_id: 2, team_name: "chobes", member_id: 103 },
  ],
  members: [
    { id: 101, sleeper_display_name: "jrayay", nickname: "Jesse" },
    { id: 103, sleeper_display_name: "chobes", nickname: null },
  ],
  players: [
    { sleeper_player_id: "9493", full_name: "Puka Nacua", position: "WR", team: "LAR", injury_status: null },
    { sleeper_player_id: "4046", full_name: "Patrick Mahomes", position: "QB", team: "KC", injury_status: null },
    { sleeper_player_id: "1111", full_name: "Bijan Robinson", position: "RB", team: "ATL", injury_status: null },
  ],
  isPending: false,
  errors: [],
  refetchAll: vi.fn(),
  ...over,
});

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

function renderPage(initialEntry = "/draft") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <DraftPage />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DraftPage", () => {
  beforeEach(() => {
    data.current = result();
  });

  it("says what is loading", () => {
    data.current = result({ isPending: true, picks: [] });
    renderPage();
    expect(screen.getByRole("status", { name: DRAFT_LOADING_LABEL })).toBeInTheDocument();
  });

  it("says there is no draft yet when the season has no picks", () => {
    data.current = result({ picks: [] });
    renderPage();
    expect(screen.getByText(NO_DRAFT_LABEL)).toBeInTheDocument();
  });

  it("lists every pick in pick order, with the price and the owner, and links each name to the board", () => {
    renderPage();
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("1");
    expect(items[0]).toHaveTextContent("Puka Nacua");
    expect(items[0]).toHaveTextContent("WR · LAR");
    expect(items[0]).toHaveTextContent("$53");
    expect(items[0]).toHaveTextContent("Jesse");
    expect(within(items[0]).getByRole("link", { name: "Puka Nacua" })).toHaveAttribute("href", "/?player=9493");
    expect(items[2]).toHaveTextContent("Bijan Robinson");
  });

  it("sums the auction in the strip", () => {
    renderPage();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("$158")).toBeInTheDocument();
  });

  it("sorts by price and writes the sort into the URL", () => {
    renderPage();
    fireEvent.click(screen.getByRole("radio", { name: "Price" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/draft?sort=price");
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Bijan Robinson");
  });

  it("groups by team with each team's spend and its unspent dollars as FAAB", () => {
    renderPage("/draft?sort=team");
    const headings = screen.getAllByRole("heading", { level: 3 });
    expect(headings[0]).toHaveTextContent("Jesse");
    expect(headings[0]).toHaveTextContent("$113 spent");
    expect(headings[0]).toHaveTextContent("$87 unspent → $435 FAAB");
    expect(headings[1]).toHaveTextContent("chobes");
  });

  it("names a failed section and keeps the list", () => {
    data.current = result({ errors: [{ section: "Players", message: "network down" }] });
    renderPage();
    expect(screen.getByText("Players could not load")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").length).toBe(3);
  });
});
```

- [ ] **Step 7: Run it to verify it fails**

Run: `pnpm --filter @ultimate-guillotine/web exec vitest run src/app/draft`
Expected: fails to resolve `./DraftPage`.

- [ ] **Step 8: Write the page**

`apps/web/src/app/draft/DraftPage.tsx`:

```tsx
import { useMemo } from "react";
import { Link, useSearchParams } from "react-router";

import { BOARD_WIDTH } from "@/board/layout";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { DraftListSkeleton } from "@/draft/components/DraftSkeleton";
import {
  draftBudgetPerTeam,
  draftRows,
  draftSummary,
  DRAFT_SORT_LABELS,
  DRAFT_SORT_MODES,
  parseDraftSortMode,
  sortDraftRows,
  teamSpend,
  type DraftRow,
  type DraftSortMode,
} from "@/draft/derive/rows";
import { useDraftPage } from "@/draft/useDraftPage";
import { REVEAL_CLASS, revealStyle } from "@/motion/reveal";

const SORT_PARAM = "sort";
export const NO_DRAFT_LABEL = "No draft yet";
const SORT_LABEL = "Sort picks by";
const META_SEPARATOR = " · ";

/** The board's own touch target for a segmented control. */
const TOUCH_TARGET_CLASS = "min-h-[44px] min-w-[44px]";

function Strip({ rows }: { rows: DraftRow[] }) {
  const summary = draftSummary(rows);
  const cells: [string, string][] = [
    ["Picks", String(summary.pickCount)],
    ["Spent", `$${summary.spent}`],
    ["Average", summary.average === null ? "—" : `$${summary.average}`],
  ];
  return (
    <dl className="grid grid-cols-3 gap-2 rounded-xl border bg-card p-3 text-center">
      {cells.map(([label, value]) => (
        <div key={label}>
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="mt-1 text-2xl leading-none figures">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function PickRow({ row, showOwner }: { row: DraftRow; showOwner: boolean }) {
  const meta = [row.position, row.nflTeam].filter(Boolean).join(META_SEPARATOR);
  return (
    <li className="flex items-center gap-3 rounded-md border bg-card px-3 py-2 text-sm">
      <span className="w-8 shrink-0 text-right text-muted-foreground figures">{row.pickNo}</span>
      <span className="flex min-w-0 flex-1 flex-col">
        {/* The board opens the card for `?player=`; a tap on a name lands there. */}
        <Link to={`/?player=${row.sleeperPlayerId}`} className="truncate font-medium hover:underline">
          {row.fullName}
        </Link>
        <span className="truncate text-xs text-muted-foreground">
          {meta}
          {showOwner && meta !== "" ? META_SEPARATOR : ""}
          {showOwner ? row.ownerName : ""}
        </span>
      </span>
      <span className="shrink-0 text-lg leading-none figures">{`$${row.amount}`}</span>
    </li>
  );
}

export function DraftPage() {
  const [params, setParams] = useSearchParams();
  const page = useDraftPage();
  const mode = parseDraftSortMode(params.get(SORT_PARAM));

  const rows = useMemo(
    () => draftRows(page.picks, page.teams, page.members, page.players),
    [page.picks, page.teams, page.members, page.players],
  );
  const sorted = useMemo(() => sortDraftRows(rows, mode), [rows, mode]);
  const spends = useMemo(
    () => teamSpend(rows, draftBudgetPerTeam(page.waiverBudget)),
    [rows, page.waiverBudget],
  );

  function changeSort(next: DraftSortMode) {
    const updated = new URLSearchParams(params);
    if (next === "pick") updated.delete(SORT_PARAM);
    else updated.set(SORT_PARAM, next);
    setParams(updated, { replace: true });
  }

  const showList = !page.isPending && rows.length > 0;

  return (
    <main className={`${BOARD_WIDTH} space-y-3 px-4 pb-10 sm:px-0`}>
      <div className={REVEAL_CLASS} style={revealStyle(0)}>
        <h2 className="text-lg font-semibold">{page.season === null ? "Draft" : `${page.season} draft`}</h2>
        <Strip rows={rows} />
      </div>

      <ToggleGroup
        type="single"
        value={mode}
        onValueChange={(value) => {
          if (value !== "") changeSort(value as DraftSortMode);
        }}
        aria-label={SORT_LABEL}
        variant="outline"
        size="sm"
        className="flex-wrap justify-start"
      >
        {DRAFT_SORT_MODES.map((option) => (
          <ToggleGroupItem key={option} value={option} aria-label={DRAFT_SORT_LABELS[option]} className={TOUCH_TARGET_CLASS}>
            {DRAFT_SORT_LABELS[option]}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

      {page.errors.map((error) => (
        <Alert key={error.section} variant="destructive">
          <AlertTitle>{error.section} could not load</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-3">
            <span>{error.message}</span>
            <Button size="sm" variant="outline" onClick={page.refetchAll}>
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      ))}

      {page.isPending ? <DraftListSkeleton revealIndex={1} /> : null}

      {!page.isPending && rows.length === 0 ? (
        <Card>
          <CardContent className="p-6">
            <p className="font-medium">{NO_DRAFT_LABEL}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              The auction lands here once it is complete and the draft sync has run.
            </p>
          </CardContent>
        </Card>
      ) : null}

      {showList && mode !== "team" ? (
        <ol className="space-y-1" aria-label="Picks">
          {sorted.map((row) => (
            <PickRow key={row.sleeperPlayerId} row={row} showOwner />
          ))}
        </ol>
      ) : null}

      {showList && mode === "team" ? (
        <div className="space-y-4">
          {spends.map((spend) => (
            <section key={spend.teamId} aria-label={spend.ownerName}>
              <h3 className="mb-1 text-sm font-medium">
                {spend.ownerName}
                <span className="text-muted-foreground">
                  {`${META_SEPARATOR}$${spend.spent} spent`}
                  {spend.unspent === null ? "" : `${META_SEPARATOR}$${spend.unspent} unspent → $${spend.faab} FAAB`}
                </span>
              </h3>
              <ol className="space-y-1" aria-label={`${spend.ownerName}'s picks`}>
                {sorted
                  .filter((row) => row.teamId === spend.teamId)
                  .map((row) => (
                    <PickRow key={row.sleeperPlayerId} row={row} showOwner={false} />
                  ))}
              </ol>
            </section>
          ))}
        </div>
      ) : null}
    </main>
  );
}
```

- [ ] **Step 9: Route, chunk, tab, fallback**

In `apps/web/src/app/lazyPages.ts` add, in the same shape as the other two, `export const DraftPage = lazy(() => import("@/app/draft/DraftPage").then((module) => ({ default: module.DraftPage })));` and a third `void import("@/app/draft/DraftPage").catch(() => undefined);` in `prefetchPages`. In `apps/web/src/router.tsx` import `DraftPage` from `@/app/lazyPages` and add `{ path: "draft", element: <DraftPage /> }` before `trades`. In `apps/web/src/app/layout.tsx` add `["/draft", "Draft", false]` after the board in `LINKS`, import `DraftPageSkeleton` from `@/draft/components/DraftSkeleton`, and add `if (pathname.startsWith("/draft")) return <DraftPageSkeleton />;` to `PageFallback`. If a layout or router test enumerates the tabs, add the fourth.

- [ ] **Step 10: Run the page test and the gates**

Run: `pnpm --filter @ultimate-guillotine/web exec tsc --noEmit && pnpm test:web && pnpm lint`
Expected: PASS. Radix renders `ToggleGroup` items as `role="radio"` inside a `radiogroup`, which is what the sort test queries.

- [ ] **Step 11: Commit**

```bash
git add apps/web/src/draft apps/web/src/app/draft apps/web/src/router.tsx apps/web/src/app/lazyPages.ts apps/web/src/app/layout.tsx
git commit -m "feat(web): a draft tab showing the whole auction"
```

---

### Task 9: Record the implementation decisions, verify on the preview

**Files:**
- Modify: `docs/superpowers/specs/2026-09-10-player-card-design.md`

- [ ] **Step 1: Append to the spec's decisions**

Under "Decisions from Ben (2026-09-10)" add a new heading `## Implementation notes (2026-09-10)`:

```markdown
## Implementation notes (2026-09-10)

- The position view's player list already sat outside its card's toggle (a 2026-09-10 change
  for the slot chips), so no restructuring was needed; both rows render the shared `PlayerName`.
- The injury tag stays as each view draws it — a titled span on the roster panel, an explained
  badge in the position view — because both are under test and neither is what this feature is
  about. `PlayerName` unifies the name and the mark, which is where the new behaviour lives.
- Closing a card opened by a tap pops the history entry that tap pushed, so the back button and
  the close button do the same thing; a card opened from a shared link replaces the URL in place,
  since there is no entry of ours to pop. The visible result is the spec's: the card closes and
  the player leaves the URL.
- The card fetches the other players a trade names in a second directory read, keyed by their
  ids, so a trade entry can say "Brock Bowers to Ray Regime" rather than an id.
- Ben (2026-09-10): "make a draft tab on the site just to show the full draft." `/draft` lists
  the season's auction in pick order, by price, or grouped by team with each team's spend and
  what its unspent dollars became in FAAB (the league's five-to-one rule, from
  `seasons.waiver_budget`). Every name links to the board's `?player=` so the card is one tap
  away. It reads the same tables the board does and nothing new.
```

- [ ] **Step 2: Full verification**

Run: `pnpm --filter @ultimate-guillotine/web exec tsc --noEmit && pnpm test:web && pnpm lint && pnpm test:agents && pnpm lint:agents`
Expected: PASS.

- [ ] **Step 3: Preview**

Start the web app (`.claude/launch.json` or `pnpm dev`) against the hosted Supabase and check at 375px: a kept player shows the anchor; Puka Nacua (`9493`) and Brock Bowers (`12534`) do not carry it on their new teams after the week-1 trade; `/?player=9493` opens on load with the draft line `$53 · pick 1 · …`, a trade entry with `T-2026-…` and its announcement if the Registrar logged one, and the numbers.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-09-10-player-card-design.md
git commit -m "docs: record the player card's implementation notes"
```

---

## Self-review

**Spec coverage.** The mark: rule in the join (Task 2), rendered by `ExplainedBadge` with the exact sentence and owner label (Task 3), in both rows (Task 3), frozen rosters (Task 2 test). The card: controlled dialog on `?player=` (Task 7), page-level mount (Task 7), the three lazy reads (Task 6 hook), header (Task 6), numbers with the caption (Tasks 4, 6), draft with the context line and Undrafted (Tasks 2, 6), journey with every entry kind, the match rule, announced entries, rescinded strike-through, the clamped quote and the code chip (Tasks 5, 6), not-rostered (Task 6), loading and error states (Task 6), season scoping (Task 5 filter; every query by `seasonId`). Privacy: only the listed tables and the registered fields `/trades` renders. Test list: every derivation and component state named in the spec has a test above.

**Draft tab (Ben, mid-plan).** Task 8: route, chunk, tab, fallback, the three sorts, the team spend with the FAAB conversion, the strip, the empty, loading and error states, and the link into the card.

**Placeholder scan.** None.

**Type consistency.** `DraftPickInfo` (types) is what `indexDraftPicks` returns, `RosterPlayer.draft` carries, `PositionPlayer.draft` copies, `auctionContext` consumes, `buildJourney` takes as `pick`, and `buildPlayerCardView` reads. `TransactionRow`/`TransactionMoveRow`/`SeasonScoreRow` are defined once in `player/fetchers.ts` and consumed by `journey.ts`, `points.ts`, `card.ts`, `usePlayerCard.ts`. `PlayerCardData` from the hook maps field-for-field onto `PlayerCardInput` in `PlayerCard`. `BoardQueryError` is reused from `useBoardData`. `onOpenPlayer: (sleeperPlayerId: string) => void` is the one signature on `RosterPanel`, `TeamCard`, `PositionView`, and the page.
