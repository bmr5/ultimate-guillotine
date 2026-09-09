# League Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a public, read-only, live-updating league board as the home page (`/`) of `apps/web` that shows all eighteen league teams sorted by this week's projected points, with expandable rosters, reading only the Supabase tables defined by the League Data Layer. The legacy rosters, rules and history pages and their direct-Sleeper hooks are deleted in the same change, so the board becomes the whole site.

**Architecture:** Eleven single-table Supabase reads (one TanStack Query hook per table, no per-team or per-player fetches) are joined in memory by id maps into a `BoardTeam[]`; an eliminated team's roster comes from the frozen `public.final_rosters` snapshot rather than its live `public.roster_holdings` rows. Every piece of logic that is not React — record aggregation, coverage caveat, sorting, elimination grouping, roster ordering, search matching — lives in pure functions under `src/board/derive/` with unit tests. One Supabase Realtime channel subscribes to the four published tables and converts bursts of postgres changes into debounced `invalidateQueries` calls; when the channel is unhealthy the queries fall back to 60-second polling and the header shows a reconnecting label.

**Tech Stack:** React 18, TypeScript 5, Vite 4, react-router-dom 6, TanStack Query 5, `@supabase/supabase-js` 2, Tailwind 3 + shadcn/Radix primitives already vendored under `src/components/ui/`, Vitest 1.6.1 + `@testing-library/react` 14 + jsdom (added by this plan — the web app currently has no test runner).

**Spec:** `docs/superpowers/specs/2026-09-09-league-board-design.md`, which reads the tables defined in `docs/superpowers/specs/2026-09-09-league-data-layer-design.md`. Read both before starting.

## Global Constraints

- The data layer is planned and built separately and **first**. This plan consumes its exact table and column names and never redefines them: `public.seasons` (extended with `scoring_settings`, `roster_positions`, `waiver_budget`, `league_synced_at`), `public.members`, `public.teams`, `public.weekly_results`, `public.players`, `public.roster_holdings`, `public.team_season_state`, `public.player_projections`, `public.team_week_projections`, `public.final_rosters`, `public.nfl_state`.
- All reads go through `apps/web/src/supabaseClient.ts` with the anon key already in `apps/web/.env` (`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`). The board never calls `api.sleeper.app` from the browser.
- The board must never read the private schema, phone numbers, member aliases (`private.member_aliases`), dues, or any table carrying message content. Nothing on the page is derived from a private source.
- The board is the home page. `apps/web/src/router.tsx` serves `BoardPage` at `/` and keeps `board` only as a redirect to `/` that preserves the query string, so already-shared `/board?sort=…` links keep working. There is no other route. `apps/web/src/app/layout.tsx` keeps only the site title and the theme toggle; there is no nav.
- The legacy site is **deleted**, not left beside the board: the rosters, rules and history pages, the old home page and its status tables, the direct-Sleeper hooks (`useLeagueRosters`, `useLeagueUsers`, `useLeagueGulagData`, `usePlayerProjections.tsx`, `usePlayerProjections_SleeperDeprecated.tsx`), the `roster-table` components they feed, `PlayerDataManager` / `PlayerDataContext` / `fetchPlayerData.js`, and the nav all go in Task 11. After that the only data code in `apps/web/src` is `src/board/`.
- Owner labels come from `public.members.nickname` when it is set, otherwise `public.members.sleeper_display_name`. Both are public columns written by the data layer. The board never selects or renders `members.display_name` — the bare Sleeper username — and never reads `private.member_aliases`.
- An eliminated team's card stays expandable and shows the frozen `public.final_rosters.holdings` snapshot taken at elimination, never its live `roster_holdings` rows, and carries an `Eliminated week N` label.
- The last-pull indicator shows a localized absolute time in the viewer's own timezone (`Updated 12:41 PM`, with the date prefixed when the pull was not today), with the relative form as smaller secondary text. The projection provider is named exactly once, in a small `Projections: Sleeper` footer line, and nowhere else — no per-card provider disclaimers.
- The board is read-only. No write, edit, or admin action; no authentication; no per-member views.
- Designed at 375 px first; everything reads as a single column at that width. Two-up at `sm`, three-up at `lg`.
- Only semantic Tailwind tokens (`bg-card`, `text-muted-foreground`, `border`, `bg-accent`); **no hard-coded hex values**. Dark mode is the existing class-strategy `ThemeProvider` (`defaultTheme="dark"`) in `apps/web/src/main.tsx`.
- Coverage gate is **95 percent**, matching the data layer and Game Pulse. A missing projection is **never rendered as zero**.
- Realtime debounce is a **750 ms trailing debounce**; backoff is **1s, 2s, 4s, capped at 30s**; polling fallback is **60 seconds**; search input debounce is **150 ms**; the burst ceiling is **eighteen** realtime-triggered refetches per window.
- The board is a `<ul>` of `<li>` cards. Each card's toggle is a real `<button>` with `aria-expanded` and `aria-controls`. The last-pull indicator is `aria-live="polite"` and announces only on a minute boundary. All expansion/reorder animation is disabled under `@media (prefers-reduced-motion: reduce)`.
- Pinned test dependency versions (checked against npm on 2026-09-09; chosen because `apps/web` is on Vite `^4.4.9` and React 18 — `vitest@5.x` and `@testing-library/react@16.x` target newer Vite/React): `vitest@1.6.1`, `jsdom@24.1.3`, `@testing-library/react@14.3.1`, `@testing-library/jest-dom@6.10.0`. Vitest gets its own `vitest.config.ts` so it never loads the app's Vite 4 config.
- Lint must stay clean: `pnpm lint` runs `eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0`. `react-refresh/only-export-components` is a warning and warnings fail the build, so a `.tsx` file may export components only — put constants and types in `.ts` files.
- `apps/web/tsconfig.json` has `strict`, `noUnusedLocals`, and `noUnusedParameters` on, and `pnpm --filter @ultimate-guillotine/web build` runs `tsc` over everything under `src` including test files.
- Commit after every task.

---

## Spec issues

Ten contradictions or gaps found while checking the board spec against the data layer spec, and against Ben's decisions of 2026-09-09 recorded at the end of both specs. Each is resolved here and the resolution is implemented in the tasks below.

1. **Two sources for record and points-for.** The board spec's Data section says record and points come from `public.weekly_results` "aggregated client-side into wins, losses, and points for", but the data layer's `public.team_season_state` already carries `wins`, `losses`, `ties`, `points_for`, `points_against` recombined from Sleeper's split integers. **Resolution:** `team_season_state` is the displayed source of record and points-for. `weekly_results` is still queried and still aggregated by a tested pure function, used as the points-for fallback when a team has no `team_season_state` row yet (Task 3, Task 6).

2. **Wins and losses cannot be derived from `weekly_results`.** That table is `(season_id, week, team_id, points, state_version, is_final)` — there is no opponent, matchup id, or head-to-head column, and a guillotine league has no head-to-head anyway. Deriving a win/loss record from it is impossible. **Resolution:** the pure aggregation function returns `{ pointsFor, weeksScored, lastFinalWeek }` only; wins/losses/ties come from `team_season_state` (Task 3).

3. **`weekly_results` can hold several rows per team-week.** Its unique key is `(season_id, week, team_id, state_version)`, so a corrected week leaves both versions in the table. Neither spec says which to use. **Resolution:** the aggregation keeps only the highest `state_version` per `(team_id, week)` and only counts rows with `is_final = true` (Task 3).

4. **Below-gate projections are both hidden and shown.** The board spec's Empty and Error States section says a coverage figure below the 95 percent gate replaces the number with an em dash, while the *next* bullet ("Partial coverage") says a figure above zero but below the gate renders the number with a "Partial projection coverage" caveat badge. The data layer is stricter still: "consumers must show 'projection unavailable' instead of a number for any provisional team." **Resolution:** the more specific "Partial coverage" bullet wins, giving three states — coverage at or above 95 renders the bare number; coverage above 0 but below 95 renders the number plus the caveat badge; coverage at 0, a null `projected_points`, or a missing row renders an em dash plus "Projection unavailable". This is exactly the softening the data layer's Open Question 5 asks Ben about. The whole rule lives in one function, `resolveProjectionDisplay`, so flipping to the strict reading is a one-function change (Task 3).

5. **Roster projections: bulk join versus fetch-on-expand.** The board spec says "One query per table, no per-team or per-player fetches" and "expansion fetches nothing extra", but the data layer says "the board fetches a team's player projections on expand and re-fetches when that team's row changes". **Resolution:** one bulk `player_projections` query for the active `(season, week)` filtered with `.in("sleeper_player_id", …)` over the union of held player ids (roughly 360 ids, one request). This honours the board spec's "one query per table" and still avoids the flood the data layer was guarding against, because `public.player_projections` is deliberately not in the realtime publication (Task 7).

6. **"Starter flag" versus the `slot` enum.** The board spec's Data section describes roster rows as carrying a "starter flag", but `public.roster_holdings.slot` is `text check (slot in ('starter','bench','ir','taxi'))`. The board spec's Expansion bullet also names only "Starters" and "bench", leaving `ir` and `taxi` unplaced. **Resolution:** `slot === 'starter'` is the starter test; the roster renders four labelled groups in the order starter, bench, injured reserve, taxi squad (Task 5).

7. **No "active season" marker exists.** The board spec filters teams "by the active `public.seasons` row", but `public.seasons` has only `id`, `year`, `sleeper_league_id`, `phase`, `rules_version`, `expected_rosters` plus the data layer's four new columns — nothing marks one row active. **Resolution:** read `public.nfl_state` first, then select the `seasons` row whose `year` equals `nfl_state.season`; every other query is keyed on that `season_id` and on `nfl_state.week` (Task 7).

8. **`team_week_projections` has no projection source or source timestamp.** The board spec's Data section asks the per-team weekly projection query to select "the projection source and source timestamp", but that table's only timestamp is `computed_at` and it has no source column — `source` and `projected_at` live on `public.player_projections`. **Resolution:** `team_week_projections.computed_at` is the board's last-pull timestamp — the newest `computed_at` across the week's rows drives the header's `Updated 12:41 PM` indicator, and each card's caveat badge keeps its own `computed_at` in a tooltip. Ben's decision 2 settles the board spec's Open Question 2: the provider is named exactly once, in a small `Projections: Sleeper` footer line, with no other provider wording anywhere on the page (Task 7, Task 9, Task 10).

9. **The data layer's `public.player_projections` collides with the legacy table of the same name.** `apps/web/src/queries/usePlayerProjections.tsx` reads `player_projections` with a completely different FantasyData shape (`player`, `game_week`, `fpts_ppr`). Typing the shared `supabase` client with the new `Database` type would make that legacy file fail `tsc` and break `pnpm build` in Tasks 2–10, while that file still exists. **Resolution:** the shared client stays untyped and `src/board/boardClient.ts` exports a typed view of it for board code only (Task 2). Task 11 deletes the legacy hook, which removes the collision, but `boardClient.ts` stays as-is — it is one line, every board module already imports it, and re-typing the shared client would be churn with no behaviour change.

10. **`public.final_rosters` does not exist yet.** Ben's data-layer decision says an eliminated team's holdings must be snapshotted at elimination and never overwritten by later Sleeper roster changes, and it leaves the shape to the plan — "a `public.final_rosters` table keyed by season and team, or an `as_of_week`/`frozen_at` marker on `roster_holdings`". This plan needs one concrete shape to type and query. **Resolution:** the board is written against a table, not a marker:

    ```sql
    public.final_rosters (
      season_id       bigint  not null references public.seasons (id),
      team_id         bigint  not null references public.teams (id),
      eliminated_week integer not null,
      holdings        jsonb   not null,
      frozen_at       timestamptz not null,
      primary key (season_id, team_id)
    )
    ```

    `holdings` is a JSON array whose entries mirror the `roster_holdings` columns the board already reads — `{ "sleeper_player_id": string, "slot": "starter" | "bench" | "ir" | "taxi", "slot_index": number | null, "lineup_position": string | null }` — so one `RosterPlayer` builder serves both live and frozen rosters. The table is anon-readable like the rest of the board's tables and is **not** in the realtime publication; a new snapshot arrives with the `team_season_state` change that marks the team eliminated, so Task 8 invalidates the final-rosters query alongside the state query.

    **The data layer plan must provide exactly that table, with exactly those column names and exactly that `holdings` entry shape.** If it instead lands the `frozen_at` marker on `roster_holdings`, this plan's Task 2 type, Task 7 fetcher and Task 6 join all change together and Task 6's frozen-roster tests are the ones that fail first. Raise it against the data layer plan before starting Task 2.

---

## File Structure

**New, all under `apps/web/`:**

| File | Responsibility |
| --- | --- |
| `vitest.config.ts` | Vitest-only config: jsdom environment, setup file, the same `@` aliases as `vite.config.ts`. Never loaded by the app build. |
| `src/test/setup.ts` | Registers jest-dom matchers and Testing Library `cleanup` after each test. |
| `src/board/types.ts` | Hand-written `Database` type for the ten tables the board reads, plus the board's domain types and sort-mode parsing. |
| `src/board/boardClient.ts` | Typed view of the shared `supabase` client, board-only. |
| `src/board/queryKeys.ts` | Every TanStack Query key the board uses, in one place. |
| `src/board/fetchers.ts` | One async fetcher per table; takes the client, returns rows, throws a labelled `Error`. |
| `src/board/useBoardData.ts` | One `useQuery` per fetcher plus the memoised join into `BoardTeam[]`. |
| `src/board/realtime.ts` | Pure realtime helpers: table list, backoff, table-to-query-key mapping. |
| `src/board/useLeagueBoardRealtime.ts` | The single Realtime channel, debounced invalidation, backoff, connection state. |
| `src/board/useDebouncedValue.ts` | Generic 150 ms value debounce for the search field. |
| `src/board/derive/time.ts` | Localized absolute last-pull formatting, the relative secondary form, staleness, minute-boundary test. |
| `src/board/derive/records.ts` | `weekly_results` aggregation. |
| `src/board/derive/projection.ts` | The coverage caveat rule. |
| `src/board/derive/sort.ts` | Sorting and eliminated grouping. |
| `src/board/derive/roster.ts` | Roster ordering and slot grouping. |
| `src/board/derive/search.ts` | Search matcher across owner, team, and player name. |
| `src/board/derive/join.ts` | Id-map join of the ten row sets into `BoardTeam[]`. |
| `src/board/components/TeamCard.tsx` | One team's card and its collapsible roster trigger. |
| `src/board/components/RosterPanel.tsx` | The nested roster list and memoised player rows. |
| `src/board/components/BoardHeader.tsx` | Sticky header: week, sort toggles, search, last-pull indicator. |
| `src/board/components/BoardStates.tsx` | Skeleton, empty, error, stale, and realtime-disconnected states. |
| `src/app/board/BoardPage.tsx` | Page assembly, UI state (sort in the URL, search, open cards) and the `Projections: Sleeper` footer. Rendered at `/`. |

**Modified:** `apps/web/package.json` (dev deps + `test` script), root `package.json` (`test:web`), `apps/web/tsconfig.node.json` (include `vitest.config.ts`), `apps/web/src/globals.css` (reduced-motion rule), `apps/web/src/router.tsx` (board at `/`, `board` redirect), `apps/web/src/app/layout.tsx` (title + theme toggle only), `apps/web/src/main.tsx` (drop `PlayerDataProvider`).

**Deleted in Task 11 — thirty files, all paths relative to `apps/web/`:**

| Group | Files |
| --- | --- |
| Pages | `src/app/home/HomePage.tsx`, `src/app/rosters/RostersPage.tsx`, `src/app/rules/RulesPage.tsx`, `src/app/rules/LeagueScheduleTable.tsx`, `src/app/rules/guillotine-league-rules.md`, `src/app/history/HistoryPage.tsx` |
| Home-page parts | `src/app/home/HeaderAnalytics.tsx`, `src/app/home/RosterCard.tsx`, `src/app/home/getCurrentGulag.ts` |
| Nav | `src/app/home/Nav.tsx`, `src/app/home/MobileNav.tsx`, `src/app/home/nav-items.ts` |
| Status tables | `src/app/status/LeagueStatus.tsx`, `src/app/status/MobileLeagueStatus.tsx`, `src/app/status/generateLeagueStatusData.tsx` |
| Hard-coded league config | `src/app/constants.ts` |
| Direct-Sleeper hooks | `src/queries/useLeagueRosters.tsx`, `src/queries/useLeagueUsers.tsx`, `src/queries/useLeagueGulagData.tsx`, `src/queries/usePlayerProjections.tsx`, `src/queries/usePlayerProjections_SleeperDeprecated.tsx` |
| Roster table components | `src/components/roster-table/RosterGrid.tsx`, `src/components/roster-table/RosterTable.tsx`, `src/components/roster-table/TeamRosterCard.tsx`, `src/components/roster-table/getOwnerByRosterId.ts`, `src/components/roster-table/getRosterData.ts`, `src/components/roster-table/useGetPlayersFromRoster.ts` |
| Local player-JSON pipeline | `src/components/PlayerDataManager.tsx`, `src/app/PlayerDataContext.tsx`, `fetchPlayerData.js` |

Nothing outside that list is touched. `src/components/mode-toggle.tsx`, `src/components/icons.tsx`, `src/components/theme-provider.tsx`, `src/components/theme-context.ts`, `src/components/tailwind-indicator.tsx`, `src/app/error-page.tsx`, `src/QueryProvider.tsx`, `src/supabaseClient.ts` and everything under `src/components/ui/` all **stay**.

---

### Task 1: Vitest harness and the last-pull formatter

The web app has no test runner. This task adds one and proves it with the first real board function — the last-pull text the sticky header needs. Per Ben's decision 2 the primary form is a localized absolute time in the viewer's own timezone (`Updated 12:41 PM`, with the date prefixed when the pull was not today) and the relative form is secondary text, so `time.ts` produces both.

**Files:**
- Modify: `apps/web/package.json` (devDependencies, `scripts`)
- Modify: `package.json` (root `scripts`)
- Modify: `apps/web/tsconfig.node.json`
- Create: `apps/web/vitest.config.ts`
- Create: `apps/web/src/test/setup.ts`
- Create: `apps/web/src/board/derive/time.ts`
- Test: `apps/web/src/board/derive/time.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `pnpm test:web` at the repo root and `pnpm --filter @ultimate-guillotine/web test`. From `src/board/derive/time.ts`: `STALE_AFTER_MS: number`, `TimeFormatOptions`, `formatUpdatedAt(updatedAt: number | null, now: number, options?: TimeFormatOptions): string`, `formatUpdatedAgo(updatedAt: number | null, now: number): string`, `isStale(updatedAt: number | null, now: number, thresholdMs?: number): boolean`, `crossesMinuteBoundary(previousElapsedMs: number, nextElapsedMs: number): boolean`.

- [ ] **Step 1: Install the pinned test dependencies**

```bash
pnpm --filter @ultimate-guillotine/web add -D \
  vitest@1.6.1 \
  jsdom@24.1.3 \
  @testing-library/react@14.3.1 \
  @testing-library/jest-dom@6.10.0
```

- [ ] **Step 2: Create the Vitest config**

Create `apps/web/vitest.config.ts`. It deliberately does not import `vite.config.ts`: Vitest 1.x brings its own Vite 5, and loading the app's Vite 4 config through it is the one thing that can go wrong. The aliases below mirror `vite.config.ts` exactly.

```ts
import path from "path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@/assets": path.resolve(__dirname, "./src/assets"),
      "@/components": path.resolve(__dirname, "./src/components"),
      "@/ui": path.resolve(__dirname, "./src/components/ui"),
      "@/lib": path.resolve(__dirname, "./src/lib"),
      "@/hooks": path.resolve(__dirname, "./src/lib/hooks"),
    },
  },
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    globals: false,
    restoreMocks: true,
  },
});
```

- [ ] **Step 3: Create the test setup file**

Create `apps/web/src/test/setup.ts`. `globals: false` means Testing Library cannot auto-register its cleanup, so it is registered here.

```ts
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
```

- [ ] **Step 4: Add the test scripts and include the new config in tsconfig.node.json**

In `apps/web/package.json`, add to `scripts` (beside the existing `lint`):

```json
    "test": "vitest run",
    "test:watch": "vitest"
```

In the root `package.json`, add to `scripts` beside `test:agents`:

```json
    "test:web": "pnpm --filter @ultimate-guillotine/web test"
```

Replace the contents of `apps/web/tsconfig.node.json` with:

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts", "vitest.config.ts"]
}
```

- [ ] **Step 5: Write the failing test**

Create `apps/web/src/board/derive/time.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import {
  crossesMinuteBoundary,
  formatUpdatedAgo,
  formatUpdatedAt,
  isStale,
  STALE_AFTER_MS,
  type TimeFormatOptions,
} from "./time";

/** 2026-09-09T16:41:20Z — 12:41 PM in New York. */
const NOW = 1_788_972_080_000;

/** Node's ICU puts U+202F before AM/PM; the assertions compare plain spaces. */
const plain = (value: string) => value.replace(/[\u202f\u00a0]/g, " ");

const NY: TimeFormatOptions = { locales: "en-US", timeZone: "America/New_York" };

describe("formatUpdatedAt", () => {
  it("shows a clock time alone for a pull made today, in the viewer's zone", () => {
    expect(plain(formatUpdatedAt(NOW, NOW, NY))).toBe("Updated 12:41 PM");
  });

  it("renders the same instant in the viewer's own timezone", () => {
    expect(
      plain(formatUpdatedAt(NOW, NOW, { locales: "en-US", timeZone: "America/Los_Angeles" })),
    ).toBe("Updated 9:41 AM");
  });

  it("prefixes the date once the pull is not today", () => {
    const yesterday = NOW - 24 * 60 * 60 * 1000;
    expect(plain(formatUpdatedAt(yesterday, NOW, NY))).toBe("Updated Sep 8, 12:41 PM");
  });

  it("says so plainly when nothing has been pulled", () => {
    expect(formatUpdatedAt(null, NOW, NY)).toBe("Not updated yet");
  });
});

describe("formatUpdatedAgo", () => {
  it("says never when nothing has loaded", () => {
    expect(formatUpdatedAgo(null, NOW)).toBe("never");
  });

  it("says just now under five seconds", () => {
    expect(formatUpdatedAgo(NOW - 2_000, NOW)).toBe("just now");
  });

  it("counts seconds up to ninety", () => {
    expect(formatUpdatedAgo(NOW - 45_000, NOW)).toBe("45 sec ago");
    expect(formatUpdatedAgo(NOW - 89_000, NOW)).toBe("89 sec ago");
  });

  it("switches to minutes past ninety seconds", () => {
    expect(formatUpdatedAgo(NOW - 90_000, NOW)).toBe("1 min ago");
    expect(formatUpdatedAgo(NOW - 125_000, NOW)).toBe("2 min ago");
  });

  it("switches to hours past ninety minutes", () => {
    expect(formatUpdatedAgo(NOW - 3 * 60 * 60_000, NOW)).toBe("3 hr ago");
  });

  it("never reports a negative age when the clock jitters", () => {
    expect(formatUpdatedAgo(NOW + 5_000, NOW)).toBe("just now");
  });
});

describe("isStale", () => {
  it("is stale past thirty minutes", () => {
    expect(isStale(NOW - STALE_AFTER_MS - 1, NOW)).toBe(true);
  });

  it("is fresh inside thirty minutes", () => {
    expect(isStale(NOW - 29 * 60_000, NOW)).toBe(false);
  });

  it("treats never-loaded as stale", () => {
    expect(isStale(null, NOW)).toBe(true);
  });
});

describe("crossesMinuteBoundary", () => {
  it("is true only when the whole-minute count changes", () => {
    expect(crossesMinuteBoundary(59_999, 60_001)).toBe(true);
    expect(crossesMinuteBoundary(1_000, 2_000)).toBe(false);
  });
});
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `pnpm --filter @ultimate-guillotine/web test`
Expected: FAIL — `Failed to resolve import "./time"`.

- [ ] **Step 7: Write the implementation**

Create `apps/web/src/board/derive/time.ts`:

```ts
/** The data layer's staleness threshold: past this, the board shows a stale badge. */
export const STALE_AFTER_MS = 30 * 60 * 1000;

/**
 * Left undefined in the app so `Intl` uses the viewer's own locale and timezone. Tests pass
 * both explicitly, because otherwise the expected string depends on the machine running them.
 */
export interface TimeFormatOptions {
  locales?: string | string[];
  timeZone?: string;
}

/** Calendar day in the formatting timezone, as a sortable key. */
function dayKey(value: Date, options: TimeFormatOptions): string {
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: options.timeZone,
  }).format(value);
}

/**
 * The primary last-pull text: the absolute time the projections were pulled, localized to the
 * viewer. A pull made today is just the clock time; anything older carries its date, because
 * `Updated 12:41 PM` on a three-day-old pull would read as fresh.
 */
export function formatUpdatedAt(
  updatedAt: number | null,
  now: number,
  options: TimeFormatOptions = {},
): string {
  if (updatedAt === null) {
    return "Not updated yet";
  }
  const then = new Date(updatedAt);
  const time = new Intl.DateTimeFormat(options.locales, {
    hour: "numeric",
    minute: "2-digit",
    timeZone: options.timeZone,
  }).format(then);
  if (dayKey(then, options) === dayKey(new Date(now), options)) {
    return `Updated ${time}`;
  }
  const date = new Intl.DateTimeFormat(options.locales, {
    month: "short",
    day: "numeric",
    timeZone: options.timeZone,
  }).format(then);
  return `Updated ${date}, ${time}`;
}

/** The secondary form, shown smaller beside the absolute time. */
export function formatUpdatedAgo(updatedAt: number | null, now: number): string {
  if (updatedAt === null) {
    return "never";
  }
  const seconds = Math.floor(Math.max(0, now - updatedAt) / 1000);
  if (seconds < 5) {
    return "just now";
  }
  if (seconds < 90) {
    return `${seconds} sec ago`;
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 90) {
    return `${minutes} min ago`;
  }
  return `${Math.floor(minutes / 60)} hr ago`;
}

export function isStale(
  updatedAt: number | null,
  now: number,
  thresholdMs: number = STALE_AFTER_MS,
): boolean {
  if (updatedAt === null) {
    return true;
  }
  return now - updatedAt > thresholdMs;
}

/**
 * The last-pull indicator ticks every second but is an aria-live region, so it
 * must only announce when the spoken text actually changes — once a minute.
 */
export function crossesMinuteBoundary(
  previousElapsedMs: number,
  nextElapsedMs: number,
): boolean {
  return Math.floor(previousElapsedMs / 60_000) !== Math.floor(nextElapsedMs / 60_000);
}
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `pnpm --filter @ultimate-guillotine/web test`
Expected: PASS — 10 tests in `time.test.ts` across four groups.

- [ ] **Step 9: Run lint and commit**

```bash
pnpm lint
git add apps/web/package.json apps/web/vitest.config.ts apps/web/tsconfig.node.json \
  apps/web/src/test/setup.ts apps/web/src/board/derive/time.ts \
  apps/web/src/board/derive/time.test.ts package.json pnpm-lock.yaml
git commit -m "test: add vitest to the web app with the board time helpers"
```

---

### Task 2: Database and board domain types

Hand-written `Database` type covering exactly the eleven tables the board reads, the domain types every later task shares, and the sort-mode parsing the URL query string needs. Per Spec issue 9 the shared `supabase` client stays untyped; board code uses a typed view. `members` carries the two public label columns from Ben's data-layer decision (`nickname`, `sleeper_display_name`) and `final_rosters` is the frozen-snapshot table from Spec issue 10.

**Files:**
- Create: `apps/web/src/board/types.ts`
- Create: `apps/web/src/board/boardClient.ts`
- Test: `apps/web/src/board/types.test.ts`

**Interfaces:**
- Consumes: `supabase` from `apps/web/src/supabaseClient.ts`.
- Produces: `Database`, `Json`, `RosterSlot`, `EliminationSource`, `FinalRosterHolding`, `RosterPlayer`, `BoardTeam`, `SortMode`, `SORT_MODES`, `DEFAULT_SORT_MODE`, `SORT_MODE_LABELS`, `parseSortMode(raw: string | null | undefined): SortMode`, `TableRow<T>`; and `boardClient: SupabaseClient<Database>` from `boardClient.ts`.

- [ ] **Step 1: Write the failing test**

Create `apps/web/src/board/types.test.ts`. The first test is a real compile-time guard: it fails `tsc` if any column name drifts from the data layer's migration.

```ts
import { describe, expect, it } from "vitest";

import {
  DEFAULT_SORT_MODE,
  parseSortMode,
  SORT_MODE_LABELS,
  SORT_MODES,
  type TableRow,
} from "./types";

describe("Database row types", () => {
  it("names every column the board reads on team_week_projections", () => {
    const row: TableRow<"team_week_projections"> = {
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
    };
    expect(row.is_provisional).toBe(false);
    expect(row.coverage_pct).toBe(100);
  });

  it("names every column the board reads on team_season_state", () => {
    const row: TableRow<"team_season_state"> = {
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
    };
    expect(row.faab_remaining).toBe(75);
  });

  it("names every column the board reads on roster_holdings", () => {
    const row: TableRow<"roster_holdings"> = {
      season_id: 1,
      team_id: 7,
      sleeper_player_id: "4046",
      slot: "starter",
      slot_index: 0,
      lineup_position: "QB",
      synced_at: "2026-09-09T12:00:00Z",
    };
    expect(row.slot).toBe("starter");
  });

  it("carries both public label columns on members", () => {
    const row: TableRow<"members"> = {
      id: 3,
      display_name: "benray887",
      sleeper_display_name: "benray",
      nickname: "Ben",
    };
    // display_name is typed because the column exists, but no fetcher ever selects it.
    expect(row.nickname).toBe("Ben");
    expect(row.sleeper_display_name).toBe("benray");
  });

  it("names every column the board reads on final_rosters", () => {
    const row: TableRow<"final_rosters"> = {
      season_id: 1,
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
    };
    expect(row.holdings[0].sleeper_player_id).toBe("4046");
    expect(row.eliminated_week).toBe(4);
  });
});

describe("parseSortMode", () => {
  it("accepts every supported mode", () => {
    expect(parseSortMode("projection")).toBe("projection");
    expect(parseSortMode("faab")).toBe("faab");
    expect(parseSortMode("points_for")).toBe("points_for");
  });

  it("falls back to the default for anything else", () => {
    expect(parseSortMode("bogus")).toBe(DEFAULT_SORT_MODE);
    expect(parseSortMode(null)).toBe("projection");
    expect(parseSortMode(undefined)).toBe("projection");
  });

  it("labels every mode", () => {
    expect(SORT_MODES.map((mode) => SORT_MODE_LABELS[mode])).toEqual([
      "Projection",
      "FAAB",
      "Points for",
    ]);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm --filter @ultimate-guillotine/web test src/board/types.test.ts`
Expected: FAIL — `Failed to resolve import "./types"`.

- [ ] **Step 3: Write the types**

Create `apps/web/src/board/types.ts`:

```ts
export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[];

/** The board holds anon `select` only, so Insert/Update exist purely to satisfy supabase-js. */
type ReadOnlyTable<Row extends Record<string, unknown>> = {
  Row: Row;
  Insert: Row;
  Update: Partial<Row>;
  Relationships: [];
};

export type RosterSlot = "starter" | "bench" | "ir" | "taxi";
export type EliminationSource = "adjudicator" | "sleeper_inferred" | "manual";

/**
 * One entry in `public.final_rosters.holdings`. Deliberately identical to the
 * `roster_holdings` columns the board reads, so one builder serves live and frozen rosters.
 */
export interface FinalRosterHolding {
  sleeper_player_id: string;
  slot: RosterSlot;
  slot_index: number | null;
  lineup_position: string | null;
}

export interface Database {
  public: {
    Tables: {
      seasons: ReadOnlyTable<{
        id: number;
        year: number;
        sleeper_league_id: string;
        phase: string;
        expected_rosters: number;
        waiver_budget: number | null;
        roster_positions: Json;
        league_synced_at: string | null;
      }>;
      members: ReadOnlyTable<{
        id: number;
        /**
         * The bare Sleeper username. Typed because the column exists; never selected and
         * never rendered — owner labels use nickname, then sleeper_display_name.
         */
        display_name: string;
        /** Written by `ug sleeper sync` from Sleeper's user record. */
        sleeper_display_name: string | null;
        /** Written by `ug members aliases load` as the first alias; null when none. */
        nickname: string | null;
      }>;
      teams: ReadOnlyTable<{
        id: number;
        season_id: number;
        member_id: number;
        sleeper_user_id: string;
        sleeper_roster_id: number;
        team_name: string;
      }>;
      weekly_results: ReadOnlyTable<{
        id: number;
        season_id: number;
        week: number;
        team_id: number;
        points: number;
        state_version: number;
        is_final: boolean;
      }>;
      players: ReadOnlyTable<{
        id: number;
        sleeper_player_id: string;
        full_name: string;
        position: string | null;
        team: string | null;
        active: boolean;
        synced_at: string;
      }>;
      roster_holdings: ReadOnlyTable<{
        season_id: number;
        team_id: number;
        sleeper_player_id: string;
        slot: RosterSlot;
        slot_index: number | null;
        lineup_position: string | null;
        synced_at: string;
      }>;
      /**
       * The elimination snapshot from Spec issue 10. `holdings` is the frozen roster; Sleeper
       * roster churn after elimination never touches it.
       */
      final_rosters: ReadOnlyTable<{
        season_id: number;
        team_id: number;
        eliminated_week: number;
        holdings: FinalRosterHolding[];
        frozen_at: string;
      }>;
      team_season_state: ReadOnlyTable<{
        season_id: number;
        team_id: number;
        faab_budget: number;
        faab_used: number;
        faab_remaining: number;
        wins: number;
        losses: number;
        ties: number;
        points_for: number;
        points_against: number;
        is_eliminated: boolean;
        eliminated_week: number | null;
        elimination_source: EliminationSource | null;
        state_version: number;
        synced_at: string;
      }>;
      team_week_projections: ReadOnlyTable<{
        season_id: number;
        team_id: number;
        week: number;
        projected_points: number;
        starter_slots: number;
        filled_slots: number;
        empty_slots: number;
        starters_projected: number;
        missing_projections: number;
        coverage_pct: number;
        is_provisional: boolean;
        computed_at: string;
      }>;
      player_projections: ReadOnlyTable<{
        season: number;
        week: number;
        sleeper_player_id: string;
        league_points: number | null;
        pts_ppr: number | null;
        source: string;
        coverage_flagged: boolean;
        run_coverage_pct: number | null;
        projected_at: string;
        synced_at: string;
      }>;
      nfl_state: ReadOnlyTable<{
        id: number;
        season: number;
        season_type: string;
        week: number;
        display_week: number | null;
        synced_at: string;
      }>;
    };
    Views: { [_ in never]: never };
    Functions: { [_ in never]: never };
    Enums: { [_ in never]: never };
    CompositeTypes: { [_ in never]: never };
  };
}

export type TableRow<T extends keyof Database["public"]["Tables"]> =
  Database["public"]["Tables"][T]["Row"];

export interface RosterPlayer {
  sleeperPlayerId: string;
  fullName: string;
  position: string | null;
  nflTeam: string | null;
  slot: RosterSlot;
  slotIndex: number | null;
  lineupPosition: string | null;
  /** null means "no projection", never zero. */
  projectedPoints: number | null;
}

export interface BoardTeam {
  teamId: number;
  teamName: string;
  ownerName: string;
  sleeperRosterId: number;
  projectedPoints: number | null;
  coveragePct: number | null;
  isProvisional: boolean;
  projectionComputedAt: string | null;
  faabRemaining: number | null;
  wins: number;
  losses: number;
  ties: number;
  pointsFor: number;
  isEliminated: boolean;
  eliminatedWeek: number | null;
  eliminationSource: EliminationSource | null;
  /** True when `roster` came from the frozen `final_rosters` snapshot, not live holdings. */
  isRosterFrozen: boolean;
  roster: RosterPlayer[];
}

export const SORT_MODES = ["projection", "faab", "points_for"] as const;
export type SortMode = (typeof SORT_MODES)[number];
export const DEFAULT_SORT_MODE: SortMode = "projection";

export const SORT_MODE_LABELS: Record<SortMode, string> = {
  projection: "Projection",
  faab: "FAAB",
  points_for: "Points for",
};

export function parseSortMode(raw: string | null | undefined): SortMode {
  return SORT_MODES.includes(raw as SortMode) ? (raw as SortMode) : DEFAULT_SORT_MODE;
}
```

- [ ] **Step 4: Write the typed client view**

Create `apps/web/src/board/boardClient.ts`:

```ts
import type { SupabaseClient } from "@supabase/supabase-js";

import { supabase } from "@/supabaseClient";

import type { Database } from "./types";

/**
 * The shared client stays untyped because the legacy `usePlayerProjections` hook reads a
 * `player_projections` table with a different, pre-data-layer shape. Board code uses this
 * typed view instead; nothing outside `src/board` should import it.
 */
export const boardClient = supabase as unknown as SupabaseClient<Database>;
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pnpm --filter @ultimate-guillotine/web test src/board/types.test.ts`
Expected: PASS — 8 tests.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/board/types.ts apps/web/src/board/types.test.ts apps/web/src/board/boardClient.ts
git commit -m "feat: add typed board database and domain types"
```

---

### Task 3: Weekly-results aggregation and the coverage caveat

Two pure functions, both named in the board spec's unit-test list. Per Spec issues 1–4, the aggregation deliberately does not produce wins/losses, and the caveat rule is the single place the three projection display states are decided.

**Files:**
- Create: `apps/web/src/board/derive/records.ts`
- Create: `apps/web/src/board/derive/projection.ts`
- Test: `apps/web/src/board/derive/records.test.ts`
- Test: `apps/web/src/board/derive/projection.test.ts`

**Interfaces:**
- Consumes: `BoardTeam` from `src/board/types.ts`.
- Produces: `WeeklyResultRow`, `TeamPointsSummary`, `summarizeWeeklyResults(rows: WeeklyResultRow[]): Map<number, TeamPointsSummary>`; `COVERAGE_GATE_PCT`, `PROJECTION_UNAVAILABLE_TEXT`, `ProjectionCaveat`, `ProjectionDisplay`, `ProjectionInput`, `resolveProjectionDisplay(input: ProjectionInput): ProjectionDisplay`.

- [ ] **Step 1: Write the failing tests**

Create `apps/web/src/board/derive/records.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { summarizeWeeklyResults, type WeeklyResultRow } from "./records";

const row = (over: Partial<WeeklyResultRow>): WeeklyResultRow => ({
  week: 1,
  team_id: 1,
  points: 100,
  is_final: true,
  state_version: 1,
  ...over,
});

describe("summarizeWeeklyResults", () => {
  it("sums points for across final weeks", () => {
    const summaries = summarizeWeeklyResults([
      row({ week: 1, team_id: 1, points: 101.25 }),
      row({ week: 2, team_id: 1, points: 98.5 }),
      row({ week: 1, team_id: 2, points: 88.1 }),
    ]);
    expect(summaries.get(1)).toEqual({
      pointsFor: 199.75,
      weeksScored: 2,
      lastFinalWeek: 2,
    });
    expect(summaries.get(2)?.pointsFor).toBe(88.1);
  });

  it("keeps only the highest state_version for a team-week", () => {
    const summaries = summarizeWeeklyResults([
      row({ week: 1, team_id: 1, points: 90, state_version: 1 }),
      row({ week: 1, team_id: 1, points: 120, state_version: 2 }),
    ]);
    expect(summaries.get(1)?.pointsFor).toBe(120);
    expect(summaries.get(1)?.weeksScored).toBe(1);
  });

  it("ignores weeks that are not final", () => {
    const summaries = summarizeWeeklyResults([
      row({ week: 1, team_id: 1, points: 90, is_final: true }),
      row({ week: 2, team_id: 1, points: 60, is_final: false }),
    ]);
    expect(summaries.get(1)).toEqual({
      pointsFor: 90,
      weeksScored: 1,
      lastFinalWeek: 1,
    });
  });

  it("returns an empty map for no rows", () => {
    expect(summarizeWeeklyResults([]).size).toBe(0);
  });
});
```

Create `apps/web/src/board/derive/projection.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { resolveProjectionDisplay } from "./projection";

describe("resolveProjectionDisplay", () => {
  it("shows the bare number at or above the 95 percent gate", () => {
    expect(
      resolveProjectionDisplay({
        projectedPoints: 112.44,
        coveragePct: 100,
        isProvisional: false,
      }),
    ).toEqual({
      kind: "value",
      points: 112.44,
      text: "112.4",
      caveat: null,
      caveatLabel: null,
    });
  });

  it("shows the number with a partial caveat between zero and the gate", () => {
    const display = resolveProjectionDisplay({
      projectedPoints: 80,
      coveragePct: 66.67,
      isProvisional: true,
    });
    expect(display.kind).toBe("value");
    expect(display.text).toBe("80.0");
    expect(display.caveat).toBe("partial");
    expect(display.caveatLabel).toBe("Partial projection coverage");
  });

  it("shows an em dash when coverage is zero", () => {
    expect(
      resolveProjectionDisplay({
        projectedPoints: 0,
        coveragePct: 0,
        isProvisional: true,
      }),
    ).toEqual({
      kind: "unavailable",
      points: null,
      text: "—",
      caveat: "unavailable",
      caveatLabel: "Projection unavailable",
    });
  });

  it("shows an em dash when there is no projection row at all", () => {
    const display = resolveProjectionDisplay({
      projectedPoints: null,
      coveragePct: null,
      isProvisional: true,
    });
    expect(display.kind).toBe("unavailable");
    expect(display.points).toBeNull();
  });

  it("never renders a missing projection as zero", () => {
    const display = resolveProjectionDisplay({
      projectedPoints: null,
      coveragePct: null,
      isProvisional: true,
    });
    expect(display.text).not.toBe("0.0");
    expect(display.text).toBe("—");
  });

  it("treats a below-gate coverage figure as partial even if the flag lags", () => {
    const display = resolveProjectionDisplay({
      projectedPoints: 70,
      coveragePct: 94.9,
      isProvisional: false,
    });
    expect(display.caveat).toBe("partial");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm --filter @ultimate-guillotine/web test src/board/derive`
Expected: FAIL — cannot resolve `./records` and `./projection`.

- [ ] **Step 3: Write the record aggregation**

Create `apps/web/src/board/derive/records.ts`:

```ts
export interface WeeklyResultRow {
  week: number;
  team_id: number;
  points: number;
  is_final: boolean;
  state_version: number;
}

/**
 * `public.weekly_results` has no opponent or matchup column, so a win/loss record cannot be
 * derived from it — that comes from `public.team_season_state`. This produces the points-for
 * fallback used when a team has no state row yet.
 */
export interface TeamPointsSummary {
  pointsFor: number;
  weeksScored: number;
  lastFinalWeek: number | null;
}

export function summarizeWeeklyResults(
  rows: WeeklyResultRow[],
): Map<number, TeamPointsSummary> {
  // A corrected week leaves both state_versions in the table; keep the newest per team-week.
  const newest = new Map<string, WeeklyResultRow>();
  for (const row of rows) {
    const key = `${row.team_id}:${row.week}`;
    const existing = newest.get(key);
    if (existing === undefined || row.state_version > existing.state_version) {
      newest.set(key, row);
    }
  }

  const summaries = new Map<number, TeamPointsSummary>();
  for (const row of newest.values()) {
    if (!row.is_final) {
      continue;
    }
    const current = summaries.get(row.team_id) ?? {
      pointsFor: 0,
      weeksScored: 0,
      lastFinalWeek: null,
    };
    summaries.set(row.team_id, {
      pointsFor: Math.round((current.pointsFor + row.points) * 100) / 100,
      weeksScored: current.weeksScored + 1,
      lastFinalWeek:
        current.lastFinalWeek === null
          ? row.week
          : Math.max(current.lastFinalWeek, row.week),
    });
  }
  return summaries;
}
```

- [ ] **Step 4: Write the coverage caveat rule**

Create `apps/web/src/board/derive/projection.ts`:

```ts
import type { BoardTeam } from "../types";

/** The same 95 percent gate the data layer and Game Pulse use. */
export const COVERAGE_GATE_PCT = 95;
export const PROJECTION_UNAVAILABLE_TEXT = "—";

export type ProjectionCaveat = "partial" | "unavailable";

export interface ProjectionDisplay {
  kind: "value" | "unavailable";
  points: number | null;
  text: string;
  caveat: ProjectionCaveat | null;
  caveatLabel: string | null;
}

export type ProjectionInput = Pick<
  BoardTeam,
  "projectedPoints" | "coveragePct" | "isProvisional"
>;

/**
 * The single place the board decides how a projection is displayed. Three states:
 * at or above the gate → bare number; above zero but below the gate → number plus caveat
 * badge; zero coverage or no row → em dash. Never zero for a missing projection.
 */
export function resolveProjectionDisplay(input: ProjectionInput): ProjectionDisplay {
  const { projectedPoints, coveragePct, isProvisional } = input;

  if (projectedPoints === null || coveragePct === null || coveragePct <= 0) {
    return {
      kind: "unavailable",
      points: null,
      text: PROJECTION_UNAVAILABLE_TEXT,
      caveat: "unavailable",
      caveatLabel: "Projection unavailable",
    };
  }

  const isPartial = isProvisional || coveragePct < COVERAGE_GATE_PCT;
  return {
    kind: "value",
    points: projectedPoints,
    text: projectedPoints.toFixed(1),
    caveat: isPartial ? "partial" : null,
    caveatLabel: isPartial ? "Partial projection coverage" : null,
  };
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pnpm --filter @ultimate-guillotine/web test src/board/derive`
Expected: PASS — 10 tests across `records.test.ts`, `projection.test.ts`, and `time.test.ts`.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/board/derive/records.ts apps/web/src/board/derive/records.test.ts \
  apps/web/src/board/derive/projection.ts apps/web/src/board/derive/projection.test.ts
git commit -m "feat: add board record aggregation and coverage caveat rule"
```

---

### Task 4: Sorting and eliminated grouping

Sort by projection, FAAB, or points for — always descending, missing projection last and never coerced to zero, eliminated teams grouped after all active teams under every sort. Plus the fallback to points-for when no team has a usable projection.

**Files:**
- Create: `apps/web/src/board/derive/sort.ts`
- Test: `apps/web/src/board/derive/sort.test.ts`

**Interfaces:**
- Consumes: `BoardTeam`, `SortMode` from `src/board/types.ts`; `resolveProjectionDisplay` from `./projection`.
- Produces: `sortValue(team: BoardTeam, mode: SortMode): number | null`, `compareTeams(a: BoardTeam, b: BoardTeam, mode: SortMode): number`, `partitionByElimination(teams: BoardTeam[]): { active: BoardTeam[]; eliminated: BoardTeam[] }`, `sortBoardTeams(teams: BoardTeam[], mode: SortMode): { active: BoardTeam[]; eliminated: BoardTeam[] }`, `selectEffectiveSortMode(teams: BoardTeam[], requested: SortMode): { mode: SortMode; fellBack: boolean }`.

- [ ] **Step 1: Write the failing test**

Create `apps/web/src/board/derive/sort.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import type { BoardTeam } from "../types";
import {
  partitionByElimination,
  selectEffectiveSortMode,
  sortBoardTeams,
} from "./sort";

const team = (over: Partial<BoardTeam> & { teamId: number }): BoardTeam => ({
  isRosterFrozen: false,
  teamName: `Team ${over.teamId}`,
  ownerName: `Owner ${over.teamId}`,
  sleeperRosterId: over.teamId,
  projectedPoints: 100,
  coveragePct: 100,
  isProvisional: false,
  projectionComputedAt: "2026-09-09T12:00:00Z",
  faabRemaining: 50,
  wins: 0,
  losses: 0,
  ties: 0,
  pointsFor: 200,
  isEliminated: false,
  eliminatedWeek: null,
  eliminationSource: null,
  roster: [],
  ...over,
});

describe("sortBoardTeams", () => {
  it("sorts active teams by projection descending", () => {
    const { active } = sortBoardTeams(
      [
        team({ teamId: 1, projectedPoints: 90 }),
        team({ teamId: 2, projectedPoints: 130 }),
        team({ teamId: 3, projectedPoints: 110 }),
      ],
      "projection",
    );
    expect(active.map((t) => t.teamId)).toEqual([2, 3, 1]);
  });

  it("sorts by FAAB descending", () => {
    const { active } = sortBoardTeams(
      [
        team({ teamId: 1, faabRemaining: 10 }),
        team({ teamId: 2, faabRemaining: 99 }),
        team({ teamId: 3, faabRemaining: 55 }),
      ],
      "faab",
    );
    expect(active.map((t) => t.teamId)).toEqual([2, 3, 1]);
  });

  it("sorts by points for descending", () => {
    const { active } = sortBoardTeams(
      [
        team({ teamId: 1, pointsFor: 305 }),
        team({ teamId: 2, pointsFor: 180 }),
        team({ teamId: 3, pointsFor: 402 }),
      ],
      "points_for",
    );
    expect(active.map((t) => t.teamId)).toEqual([3, 1, 2]);
  });

  it("puts a missing projection last instead of treating it as zero", () => {
    const { active } = sortBoardTeams(
      [
        team({ teamId: 1, projectedPoints: null, coveragePct: null, isProvisional: true }),
        team({ teamId: 2, projectedPoints: -5 }),
        team({ teamId: 3, projectedPoints: 40 }),
      ],
      "projection",
    );
    expect(active.map((t) => t.teamId)).toEqual([3, 2, 1]);
  });

  it("groups eliminated teams after every active team under every sort", () => {
    const teams = [
      team({ teamId: 1, projectedPoints: 200, isEliminated: true, eliminatedWeek: 2 }),
      team({ teamId: 2, projectedPoints: 10 }),
      team({ teamId: 3, projectedPoints: 180, isEliminated: true, eliminatedWeek: 5 }),
    ];
    const byProjection = sortBoardTeams(teams, "projection");
    expect(byProjection.active.map((t) => t.teamId)).toEqual([2]);
    expect(byProjection.eliminated.map((t) => t.teamId)).toEqual([3, 1]);

    const byFaab = sortBoardTeams(teams, "faab");
    expect(byFaab.active.map((t) => t.teamId)).toEqual([2]);
    expect(byFaab.eliminated.map((t) => t.teamId)).toEqual([3, 1]);
  });

  it("breaks ties on points for, then team name", () => {
    const { active } = sortBoardTeams(
      [
        team({ teamId: 1, teamName: "Zeta", projectedPoints: 100, pointsFor: 100 }),
        team({ teamId: 2, teamName: "Alpha", projectedPoints: 100, pointsFor: 100 }),
        team({ teamId: 3, teamName: "Beta", projectedPoints: 100, pointsFor: 300 }),
      ],
      "projection",
    );
    expect(active.map((t) => t.teamId)).toEqual([3, 2, 1]);
  });

  it("does not mutate the input array", () => {
    const teams = [team({ teamId: 1, projectedPoints: 10 }), team({ teamId: 2, projectedPoints: 20 })];
    sortBoardTeams(teams, "projection");
    expect(teams.map((t) => t.teamId)).toEqual([1, 2]);
  });
});

describe("partitionByElimination", () => {
  it("splits on the is_eliminated flag", () => {
    const { active, eliminated } = partitionByElimination([
      team({ teamId: 1 }),
      team({ teamId: 2, isEliminated: true, eliminatedWeek: 3 }),
    ]);
    expect(active.map((t) => t.teamId)).toEqual([1]);
    expect(eliminated.map((t) => t.teamId)).toEqual([2]);
  });
});

describe("selectEffectiveSortMode", () => {
  it("keeps projection when at least one team has a usable projection", () => {
    expect(
      selectEffectiveSortMode(
        [
          team({ teamId: 1, projectedPoints: null, coveragePct: null }),
          team({ teamId: 2, projectedPoints: 90 }),
        ],
        "projection",
      ),
    ).toEqual({ mode: "projection", fellBack: false });
  });

  it("falls back to points for when no projection is usable", () => {
    expect(
      selectEffectiveSortMode(
        [
          team({ teamId: 1, projectedPoints: null, coveragePct: null }),
          team({ teamId: 2, projectedPoints: null, coveragePct: 0 }),
        ],
        "projection",
      ),
    ).toEqual({ mode: "points_for", fellBack: true });
  });

  it("never overrides an explicit non-projection sort", () => {
    expect(
      selectEffectiveSortMode([team({ teamId: 1, projectedPoints: null, coveragePct: null })], "faab"),
    ).toEqual({ mode: "faab", fellBack: false });
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm --filter @ultimate-guillotine/web test src/board/derive/sort.test.ts`
Expected: FAIL — `Failed to resolve import "./sort"`.

- [ ] **Step 3: Write the implementation**

Create `apps/web/src/board/derive/sort.ts`:

```ts
import type { BoardTeam, SortMode } from "../types";
import { resolveProjectionDisplay } from "./projection";

/** null means "not comparable" and always sorts last — never coerced to zero. */
export function sortValue(team: BoardTeam, mode: SortMode): number | null {
  if (mode === "faab") {
    return team.faabRemaining;
  }
  if (mode === "points_for") {
    return team.pointsFor;
  }
  const display = resolveProjectionDisplay(team);
  return display.kind === "value" ? display.points : null;
}

export function compareTeams(a: BoardTeam, b: BoardTeam, mode: SortMode): number {
  const left = sortValue(a, mode);
  const right = sortValue(b, mode);

  if (left === null && right === null) {
    return a.teamName.localeCompare(b.teamName);
  }
  if (left === null) {
    return 1;
  }
  if (right === null) {
    return -1;
  }
  if (right !== left) {
    return right - left;
  }
  if (b.pointsFor !== a.pointsFor) {
    return b.pointsFor - a.pointsFor;
  }
  return a.teamName.localeCompare(b.teamName);
}

export function partitionByElimination(teams: BoardTeam[]): {
  active: BoardTeam[];
  eliminated: BoardTeam[];
} {
  const active: BoardTeam[] = [];
  const eliminated: BoardTeam[] = [];
  for (const team of teams) {
    if (team.isEliminated) {
      eliminated.push(team);
    } else {
      active.push(team);
    }
  }
  return { active, eliminated };
}

export function sortBoardTeams(
  teams: BoardTeam[],
  mode: SortMode,
): { active: BoardTeam[]; eliminated: BoardTeam[] } {
  const { active, eliminated } = partitionByElimination(teams);
  return {
    active: [...active].sort((a, b) => compareTeams(a, b, mode)),
    // Most recently eliminated first, so the newest casualty reads at the top of the group.
    eliminated: [...eliminated].sort((a, b) => {
      const aWeek = a.eliminatedWeek ?? 0;
      const bWeek = b.eliminatedWeek ?? 0;
      if (bWeek !== aWeek) {
        return bWeek - aWeek;
      }
      return compareTeams(a, b, mode);
    }),
  };
}

/** With projections off entirely, projection sort is meaningless; say so and use points for. */
export function selectEffectiveSortMode(
  teams: BoardTeam[],
  requested: SortMode,
): { mode: SortMode; fellBack: boolean } {
  if (requested !== "projection") {
    return { mode: requested, fellBack: false };
  }
  const hasUsableProjection = teams.some(
    (team) => resolveProjectionDisplay(team).kind === "value",
  );
  return hasUsableProjection
    ? { mode: "projection", fellBack: false }
    : { mode: "points_for", fellBack: true };
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pnpm --filter @ultimate-guillotine/web test src/board/derive/sort.test.ts`
Expected: PASS — 11 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/board/derive/sort.ts apps/web/src/board/derive/sort.test.ts
git commit -m "feat: add board sorting and eliminated grouping"
```

---

### Task 5: Roster ordering and the search matcher

Roster order (starters by lineup slot, then bench, injured reserve, taxi) and the search matcher across owner, team, and player name that also reports which players matched so the card can auto-expand to them.

**Files:**
- Create: `apps/web/src/board/derive/roster.ts`
- Create: `apps/web/src/board/derive/search.ts`
- Test: `apps/web/src/board/derive/roster.test.ts`
- Test: `apps/web/src/board/derive/search.test.ts`

**Interfaces:**
- Consumes: `BoardTeam`, `RosterPlayer`, `RosterSlot` from `src/board/types.ts`.
- Produces: `SLOT_ORDER: Record<RosterSlot, number>`, `SLOT_LABELS: Record<RosterSlot, string>`, `orderRoster(players: RosterPlayer[]): RosterPlayer[]`, `RosterGroup`, `groupRosterBySlot(players: RosterPlayer[]): RosterGroup[]`; `TeamSearchMatch`, `matchTeam(team: BoardTeam, term: string): TeamSearchMatch`, `FilteredBoard`, `filterTeams(teams: BoardTeam[], term: string): FilteredBoard`.

- [ ] **Step 1: Write the failing tests**

Create `apps/web/src/board/derive/roster.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import type { RosterPlayer } from "../types";
import { groupRosterBySlot, orderRoster } from "./roster";

const player = (over: Partial<RosterPlayer> & { sleeperPlayerId: string }): RosterPlayer => ({
  fullName: `Player ${over.sleeperPlayerId}`,
  position: "WR",
  nflTeam: "SF",
  slot: "bench",
  slotIndex: null,
  lineupPosition: null,
  projectedPoints: null,
  ...over,
});

describe("orderRoster", () => {
  it("puts starters first in lineup slot order", () => {
    const ordered = orderRoster([
      player({ sleeperPlayerId: "c", slot: "bench", projectedPoints: 20 }),
      player({ sleeperPlayerId: "b", slot: "starter", slotIndex: 1, lineupPosition: "RB" }),
      player({ sleeperPlayerId: "a", slot: "starter", slotIndex: 0, lineupPosition: "QB" }),
    ]);
    expect(ordered.map((p) => p.sleeperPlayerId)).toEqual(["a", "b", "c"]);
  });

  it("orders bench, ir, then taxi after the starters", () => {
    const ordered = orderRoster([
      player({ sleeperPlayerId: "taxi", slot: "taxi" }),
      player({ sleeperPlayerId: "ir", slot: "ir" }),
      player({ sleeperPlayerId: "bench", slot: "bench" }),
      player({ sleeperPlayerId: "start", slot: "starter", slotIndex: 0 }),
    ]);
    expect(ordered.map((p) => p.sleeperPlayerId)).toEqual(["start", "bench", "ir", "taxi"]);
  });

  it("orders non-starters by projection descending with missing projections last", () => {
    const ordered = orderRoster([
      player({ sleeperPlayerId: "none", slot: "bench", projectedPoints: null }),
      player({ sleeperPlayerId: "low", slot: "bench", projectedPoints: 3.2 }),
      player({ sleeperPlayerId: "high", slot: "bench", projectedPoints: 14.8 }),
    ]);
    expect(ordered.map((p) => p.sleeperPlayerId)).toEqual(["high", "low", "none"]);
  });

  it("does not mutate the input", () => {
    const players = [
      player({ sleeperPlayerId: "b", slot: "bench" }),
      player({ sleeperPlayerId: "a", slot: "starter", slotIndex: 0 }),
    ];
    orderRoster(players);
    expect(players.map((p) => p.sleeperPlayerId)).toEqual(["b", "a"]);
  });
});

describe("groupRosterBySlot", () => {
  it("labels each occupied slot group and skips empty ones", () => {
    const groups = groupRosterBySlot([
      player({ sleeperPlayerId: "a", slot: "starter", slotIndex: 0 }),
      player({ sleeperPlayerId: "b", slot: "bench" }),
    ]);
    expect(groups.map((g) => g.slot)).toEqual(["starter", "bench"]);
    expect(groups.map((g) => g.label)).toEqual(["Starters", "Bench"]);
    expect(groups[0].players.map((p) => p.sleeperPlayerId)).toEqual(["a"]);
  });

  it("returns nothing for an empty roster", () => {
    expect(groupRosterBySlot([])).toEqual([]);
  });
});
```

Create `apps/web/src/board/derive/search.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import type { BoardTeam, RosterPlayer } from "../types";
import { filterTeams, matchTeam } from "./search";

const player = (id: string, fullName: string): RosterPlayer => ({
  sleeperPlayerId: id,
  fullName,
  position: "RB",
  nflTeam: "SF",
  slot: "starter",
  slotIndex: 0,
  lineupPosition: "RB",
  projectedPoints: 12,
});

const team = (over: Partial<BoardTeam> & { teamId: number }): BoardTeam => ({
  isRosterFrozen: false,
  teamName: "The Choppers",
  ownerName: "benray",
  sleeperRosterId: over.teamId,
  projectedPoints: 100,
  coveragePct: 100,
  isProvisional: false,
  projectionComputedAt: null,
  faabRemaining: 50,
  wins: 0,
  losses: 0,
  ties: 0,
  pointsFor: 100,
  isEliminated: false,
  eliminatedWeek: null,
  eliminationSource: null,
  roster: [player("1", "Christian McCaffrey")],
  ...over,
});

describe("matchTeam", () => {
  it("matches everything on an empty term", () => {
    expect(matchTeam(team({ teamId: 1 }), "   ")).toEqual({
      matches: true,
      matchedPlayerIds: [],
    });
  });

  it("matches on owner display name, case-insensitively", () => {
    expect(matchTeam(team({ teamId: 1 }), "BENR").matches).toBe(true);
  });

  it("matches on team name", () => {
    expect(matchTeam(team({ teamId: 1 }), "chopper").matches).toBe(true);
  });

  it("matches on player name and reports the matched player", () => {
    const result = matchTeam(team({ teamId: 1 }), "mccaffrey");
    expect(result.matches).toBe(true);
    expect(result.matchedPlayerIds).toEqual(["1"]);
  });

  it("does not match unrelated text", () => {
    expect(matchTeam(team({ teamId: 1 }), "zzzz")).toEqual({
      matches: false,
      matchedPlayerIds: [],
    });
  });
});

describe("filterTeams", () => {
  it("keeps only matching teams and auto-expands player matches", () => {
    const teams = [
      team({ teamId: 1 }),
      team({
        teamId: 2,
        ownerName: "charlie",
        teamName: "Gulag Bound",
        roster: [player("9", "Puka Nacua")],
      }),
    ];
    const result = filterTeams(teams, "puka");
    expect(result.teams.map((t) => t.teamId)).toEqual([2]);
    expect(result.autoExpandTeamIds).toEqual([2]);
    expect([...result.matchedPlayerIds]).toEqual(["9"]);
  });

  it("does not auto-expand a team matched only by its name", () => {
    const result = filterTeams([team({ teamId: 1 })], "chopper");
    expect(result.teams.map((t) => t.teamId)).toEqual([1]);
    expect(result.autoExpandTeamIds).toEqual([]);
  });

  it("returns every team for an empty term", () => {
    const teams = [team({ teamId: 1 }), team({ teamId: 2 })];
    expect(filterTeams(teams, "").teams).toHaveLength(2);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm --filter @ultimate-guillotine/web test src/board/derive/roster.test.ts src/board/derive/search.test.ts`
Expected: FAIL — cannot resolve `./roster` and `./search`.

- [ ] **Step 3: Write the roster ordering**

Create `apps/web/src/board/derive/roster.ts`:

```ts
import type { RosterPlayer, RosterSlot } from "../types";

export const SLOT_ORDER: Record<RosterSlot, number> = {
  starter: 0,
  bench: 1,
  ir: 2,
  taxi: 3,
};

export const SLOT_LABELS: Record<RosterSlot, string> = {
  starter: "Starters",
  bench: "Bench",
  ir: "Injured reserve",
  taxi: "Taxi squad",
};

export function orderRoster(players: RosterPlayer[]): RosterPlayer[] {
  return [...players].sort((a, b) => {
    const slotDelta = SLOT_ORDER[a.slot] - SLOT_ORDER[b.slot];
    if (slotDelta !== 0) {
      return slotDelta;
    }

    if (a.slot === "starter") {
      // Starters read in the league's own lineup order, not by score.
      const left = a.slotIndex ?? Number.MAX_SAFE_INTEGER;
      const right = b.slotIndex ?? Number.MAX_SAFE_INTEGER;
      if (left !== right) {
        return left - right;
      }
      return a.fullName.localeCompare(b.fullName);
    }

    const left = a.projectedPoints;
    const right = b.projectedPoints;
    if (left === null && right === null) {
      return a.fullName.localeCompare(b.fullName);
    }
    if (left === null) {
      return 1;
    }
    if (right === null) {
      return -1;
    }
    if (right !== left) {
      return right - left;
    }
    return a.fullName.localeCompare(b.fullName);
  });
}

export interface RosterGroup {
  slot: RosterSlot;
  label: string;
  players: RosterPlayer[];
}

export function groupRosterBySlot(players: RosterPlayer[]): RosterGroup[] {
  const ordered = orderRoster(players);
  const groups: RosterGroup[] = [];
  for (const slot of ["starter", "bench", "ir", "taxi"] as const) {
    const inSlot = ordered.filter((player) => player.slot === slot);
    if (inSlot.length > 0) {
      groups.push({ slot, label: SLOT_LABELS[slot], players: inSlot });
    }
  }
  return groups;
}
```

- [ ] **Step 4: Write the search matcher**

Create `apps/web/src/board/derive/search.ts`:

```ts
import type { BoardTeam } from "../types";

export interface TeamSearchMatch {
  matches: boolean;
  matchedPlayerIds: string[];
}

export function matchTeam(team: BoardTeam, term: string): TeamSearchMatch {
  const needle = term.trim().toLowerCase();
  if (needle === "") {
    return { matches: true, matchedPlayerIds: [] };
  }

  const matchedPlayerIds = team.roster
    .filter((player) => player.fullName.toLowerCase().includes(needle))
    .map((player) => player.sleeperPlayerId);

  const nameHit =
    team.ownerName.toLowerCase().includes(needle) ||
    team.teamName.toLowerCase().includes(needle);

  return {
    matches: nameHit || matchedPlayerIds.length > 0,
    matchedPlayerIds: nameHit && matchedPlayerIds.length === 0 ? [] : matchedPlayerIds,
  };
}

export interface FilteredBoard {
  teams: BoardTeam[];
  /** Teams matched by a player name auto-expand so the matched player is visible. */
  autoExpandTeamIds: number[];
  matchedPlayerIds: Set<string>;
}

export function filterTeams(teams: BoardTeam[], term: string): FilteredBoard {
  const kept: BoardTeam[] = [];
  const autoExpandTeamIds: number[] = [];
  const matchedPlayerIds = new Set<string>();

  for (const team of teams) {
    const match = matchTeam(team, term);
    if (!match.matches) {
      continue;
    }
    kept.push(team);
    if (match.matchedPlayerIds.length > 0) {
      autoExpandTeamIds.push(team.teamId);
      for (const id of match.matchedPlayerIds) {
        matchedPlayerIds.add(id);
      }
    }
  }

  return { teams: kept, autoExpandTeamIds, matchedPlayerIds };
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pnpm --filter @ultimate-guillotine/web test src/board/derive`
Expected: PASS — 14 new tests, 25 total across `src/board/derive`.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/board/derive/roster.ts apps/web/src/board/derive/roster.test.ts \
  apps/web/src/board/derive/search.ts apps/web/src/board/derive/search.test.ts
git commit -m "feat: add roster ordering and board search matcher"
```

---

### Task 6: Owner labels and the id-map join

Turn eleven flat row sets into `BoardTeam[]` with `Map` lookups built once. This is the memoised join the board spec's Performance section requires. It applies the record and points-for resolution from Spec issues 1 and 2, Ben's decision 4 for owner labels (nickname, then Sleeper display name, never the bare username), and Ben's decision 3 for eliminated teams (the frozen `final_rosters` snapshot replaces live holdings).

**Files:**
- Create: `apps/web/src/board/derive/join.ts`
- Test: `apps/web/src/board/derive/join.test.ts`

**Interfaces:**
- Consumes: `TableRow`, `BoardTeam`, `RosterPlayer`, `FinalRosterHolding` from `src/board/types.ts`; `summarizeWeeklyResults`, `WeeklyResultRow` from `./records`; `orderRoster` from `./roster`.
- Produces: `OwnerLabelSource`, `resolveOwnerLabel(member: OwnerLabelSource | undefined): string`, `BoardRawData`, `joinBoardTeams(raw: BoardRawData): BoardTeam[]`.

- [ ] **Step 1: Write the failing test**

Create `apps/web/src/board/derive/join.test.ts`:

```ts
import { describe, expect, it } from "vitest";

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
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm --filter @ultimate-guillotine/web test src/board/derive/join.test.ts`
Expected: FAIL — `Failed to resolve import "./join"`.

- [ ] **Step 3: Write the implementation**

Create `apps/web/src/board/derive/join.ts`:

```ts
import type {
  BoardTeam,
  FinalRosterHolding,
  RosterPlayer,
  TableRow,
} from "../types";
import { summarizeWeeklyResults, type WeeklyResultRow } from "./records";
import { orderRoster } from "./roster";

export type OwnerLabelSource = Pick<
  TableRow<"members">,
  "sleeper_display_name" | "nickname"
>;

/**
 * Ben's decision 4: the nickname from `public.members.nickname` when there is one, otherwise
 * `public.members.sleeper_display_name`. `members.display_name` — the bare Sleeper username —
 * is never a fallback, so a member with neither public label reads as "Unknown owner" rather
 * than leaking a username.
 */
export function resolveOwnerLabel(member: OwnerLabelSource | undefined): string {
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

export interface BoardRawData {
  teams: Pick<
    TableRow<"teams">,
    "id" | "member_id" | "sleeper_roster_id" | "team_name"
  >[];
  members: Pick<TableRow<"members">, "id" | "sleeper_display_name" | "nickname">[];
  teamSeasonState: TableRow<"team_season_state">[];
  teamWeekProjections: TableRow<"team_week_projections">[];
  rosterHoldings: Pick<
    TableRow<"roster_holdings">,
    "team_id" | "sleeper_player_id" | "slot" | "slot_index" | "lineup_position"
  >[];
  players: Pick<
    TableRow<"players">,
    "sleeper_player_id" | "full_name" | "position" | "team"
  >[];
  playerProjections: Pick<
    TableRow<"player_projections">,
    "sleeper_player_id" | "league_points"
  >[];
  weeklyResults: WeeklyResultRow[];
  finalRosters: Pick<
    TableRow<"final_rosters">,
    "team_id" | "eliminated_week" | "holdings" | "frozen_at"
  >[];
}

export function joinBoardTeams(raw: BoardRawData): BoardTeam[] {
  const memberById = new Map(raw.members.map((m) => [m.id, m]));
  const stateByTeamId = new Map(raw.teamSeasonState.map((s) => [s.team_id, s]));
  const finalRosterByTeamId = new Map(raw.finalRosters.map((f) => [f.team_id, f]));
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
      fullName: player?.full_name ?? `Unknown player ${holding.sleeper_player_id}`,
      position: player?.position ?? null,
      nflTeam: player?.team ?? null,
      slot: holding.slot,
      slotIndex: holding.slot_index,
      lineupPosition: holding.lineup_position,
      projectedPoints: pointsByPlayerId.get(holding.sleeper_player_id) ?? null,
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
    const frozen = isEliminated ? (finalRosterByTeamId.get(team.id) ?? null) : null;

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
      wins: state?.wins ?? 0,
      losses: state?.losses ?? 0,
      ties: state?.ties ?? 0,
      pointsFor: state === null ? (summary?.pointsFor ?? 0) : state.points_for,
      isEliminated,
      eliminatedWeek: state?.eliminated_week ?? frozen?.eliminated_week ?? null,
      eliminationSource: state?.elimination_source ?? null,
      isRosterFrozen: frozen !== null,
      roster:
        frozen === null
          ? orderRoster(rosterByTeamId.get(team.id) ?? [])
          : orderRoster(frozen.holdings.map(buildRosterPlayer)),
    };
  });
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pnpm --filter @ultimate-guillotine/web test src/board/derive/join.test.ts`
Expected: PASS — 16 tests across `resolveOwnerLabel` and `joinBoardTeams`.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/board/derive/join.ts apps/web/src/board/derive/join.test.ts
git commit -m "feat: add board owner labels and id-map join"
```

---

### Task 7: Query keys, per-table fetchers, and the data hook

One fetcher and one `useQuery` per table — eleven queries total, no per-team or per-player fetches. Per Spec issue 7 the season is resolved from `nfl_state.season`; per Spec issue 5 player projections are one bulk `.in()` query over the union of held player ids, which per Ben's decision 3 now includes the ids inside every frozen `final_rosters` snapshot as well as live holdings (a dropped player is still on an eliminated team's frozen roster). `fetchMembers` selects only the two public label columns, never `display_name`. The hook also derives `projectionsUpdatedAt` — the newest `team_week_projections.computed_at` — which is the last-pull time the header shows.

**Files:**
- Create: `apps/web/src/board/queryKeys.ts`
- Create: `apps/web/src/board/fetchers.ts`
- Create: `apps/web/src/board/useBoardData.ts`
- Test: `apps/web/src/board/fetchers.test.ts`

**Interfaces:**
- Consumes: `boardClient` from `./boardClient`; `TableRow` from `./types`; `joinBoardTeams`, `BoardRawData` from `./derive/join`.
- Produces: `boardKeys` (see below); `BoardClient`, `NflStateRow`, `SeasonRow`, `FinalRosterRow`, and one `fetchX(client, …)` per table; `BoardDataOptions`, `BoardDataResult`, `useBoardData(options: BoardDataOptions): BoardDataResult`.

- [ ] **Step 1: Write the query keys**

Create `apps/web/src/board/queryKeys.ts`. This is a plain module (no components) so the react-refresh lint rule does not apply.

```ts
export const boardKeys = {
  all: ["board"] as const,
  nflState: () => ["board", "nfl_state"] as const,
  season: (year: number) => ["board", "seasons", year] as const,
  teams: (seasonId: number) => ["board", "teams", seasonId] as const,
  members: () => ["board", "members"] as const,
  teamSeasonState: (seasonId: number) =>
    ["board", "team_season_state", seasonId] as const,
  teamWeekProjections: (seasonId: number, week: number) =>
    ["board", "team_week_projections", seasonId, week] as const,
  rosterHoldings: (seasonId: number) => ["board", "roster_holdings", seasonId] as const,
  finalRosters: (seasonId: number) => ["board", "final_rosters", seasonId] as const,
  players: (seasonId: number) => ["board", "players", seasonId] as const,
  playerProjections: (season: number, week: number) =>
    ["board", "player_projections", season, week] as const,
  weeklyResults: (seasonId: number) => ["board", "weekly_results", seasonId] as const,
};
```

- [ ] **Step 2: Write the failing fetcher test**

Create `apps/web/src/board/fetchers.test.ts`. The fake client records the table, columns, and filters each fetcher asked for, which is what actually needs pinning — a column-name drift against the data layer is the failure mode here.

```ts
import { describe, expect, it } from "vitest";

import type { BoardClient } from "./fetchers";
import {
  fetchMembers,
  fetchNflState,
  fetchPlayerProjections,
  fetchPlayers,
  fetchFinalRosters,
  fetchRosterHoldings,
  fetchSeasonByYear,
  fetchTeamSeasonState,
  fetchTeamWeekProjections,
  fetchTeams,
  fetchWeeklyResults,
} from "./fetchers";

interface Call {
  table: string;
  columns: string;
  filters: [string, unknown][];
}

function createFakeClient(
  responses: Record<string, unknown[]>,
  errors: Record<string, string> = {},
): { client: BoardClient; calls: Call[] } {
  const calls: Call[] = [];
  const client = {
    from(table: string) {
      const call: Call = { table, columns: "", filters: [] };
      calls.push(call);
      const builder = {
        select(columns: string) {
          call.columns = columns;
          return builder;
        },
        eq(column: string, value: unknown) {
          call.filters.push([column, value]);
          return builder;
        },
        in(column: string, values: unknown[]) {
          call.filters.push([column, values]);
          return builder;
        },
        then(resolve: (value: unknown) => unknown) {
          const message = errors[table];
          return Promise.resolve(
            message === undefined
              ? { data: responses[table] ?? [], error: null }
              : { data: null, error: { message } },
          ).then(resolve);
        },
      };
      return builder;
    },
  } as unknown as BoardClient;
  return { client, calls };
}

describe("fetchNflState", () => {
  it("reads the single pinned row", async () => {
    const { client, calls } = createFakeClient({
      nfl_state: [{ id: 1, season: 2026, season_type: "regular", week: 3, display_week: 3, synced_at: "t" }],
    });
    const state = await fetchNflState(client);
    expect(state?.week).toBe(3);
    expect(calls[0].table).toBe("nfl_state");
    expect(calls[0].columns).toBe("id, season, season_type, week, display_week, synced_at");
    expect(calls[0].filters).toEqual([["id", 1]]);
  });

  it("returns null when the row is missing", async () => {
    const { client } = createFakeClient({ nfl_state: [] });
    expect(await fetchNflState(client)).toBeNull();
  });

  it("throws a labelled error", async () => {
    const { client } = createFakeClient({}, { nfl_state: "boom" });
    await expect(fetchNflState(client)).rejects.toThrow("nfl_state: boom");
  });
});

describe("season and team fetchers", () => {
  it("finds the season by the nfl_state year", async () => {
    const { client, calls } = createFakeClient({
      seasons: [{ id: 1, year: 2026, sleeper_league_id: "x", phase: "regular", expected_rosters: 18, waiver_budget: 100, roster_positions: [], league_synced_at: "t" }],
    });
    const season = await fetchSeasonByYear(client, 2026);
    expect(season?.id).toBe(1);
    expect(calls[0].filters).toEqual([["year", 2026]]);
  });

  it("reads teams for the season", async () => {
    const { client, calls } = createFakeClient({ teams: [] });
    await fetchTeams(client, 1);
    expect(calls[0].table).toBe("teams");
    expect(calls[0].columns).toBe("id, sleeper_roster_id, team_name, member_id");
    expect(calls[0].filters).toEqual([["season_id", 1]]);
  });

  it("reads only the two public label columns on members, never display_name", async () => {
    const { client, calls } = createFakeClient({ members: [] });
    await fetchMembers(client);
    expect(calls[0].columns).toBe("id, sleeper_display_name, nickname");
    expect(calls[0].columns).not.toContain("display_name,");
    expect(calls[0].filters).toEqual([]);
  });
});

describe("state, projection and roster fetchers", () => {
  it("reads team_season_state for the season", async () => {
    const { client, calls } = createFakeClient({ team_season_state: [] });
    await fetchTeamSeasonState(client, 1);
    expect(calls[0].columns).toContain("faab_remaining");
    expect(calls[0].columns).toContain("eliminated_week");
    expect(calls[0].filters).toEqual([["season_id", 1]]);
  });

  it("reads team_week_projections for the season and week", async () => {
    const { client, calls } = createFakeClient({ team_week_projections: [] });
    await fetchTeamWeekProjections(client, 1, 3);
    expect(calls[0].columns).toContain("coverage_pct");
    expect(calls[0].columns).toContain("is_provisional");
    expect(calls[0].filters).toEqual([
      ["season_id", 1],
      ["week", 3],
    ]);
  });

  it("reads roster_holdings for the season", async () => {
    const { client, calls } = createFakeClient({ roster_holdings: [] });
    await fetchRosterHoldings(client, 1);
    expect(calls[0].columns).toBe(
      "team_id, sleeper_player_id, slot, slot_index, lineup_position",
    );
  });

  it("reads weekly_results for the season", async () => {
    const { client, calls } = createFakeClient({ weekly_results: [] });
    await fetchWeeklyResults(client, 1);
    expect(calls[0].columns).toBe("week, team_id, points, is_final, state_version");
  });

  it("reads the frozen final rosters for the season", async () => {
    const { client, calls } = createFakeClient({ final_rosters: [] });
    await fetchFinalRosters(client, 1);
    expect(calls[0].table).toBe("final_rosters");
    expect(calls[0].columns).toBe(
      "team_id, eliminated_week, holdings, frozen_at",
    );
    expect(calls[0].filters).toEqual([["season_id", 1]]);
  });
});

describe("bulk player fetchers", () => {
  it("fetches every held player in one request", async () => {
    const { client, calls } = createFakeClient({ players: [] });
    await fetchPlayers(client, ["4046", "9999"]);
    expect(calls).toHaveLength(1);
    expect(calls[0].filters).toEqual([["sleeper_player_id", ["4046", "9999"]]]);
  });

  it("fetches every held player's projection in one request", async () => {
    const { client, calls } = createFakeClient({ player_projections: [] });
    await fetchPlayerProjections(client, 2026, 3, ["4046"]);
    expect(calls).toHaveLength(1);
    expect(calls[0].columns).toBe("sleeper_player_id, league_points");
    expect(calls[0].filters).toEqual([
      ["season", 2026],
      ["week", 3],
      ["sleeper_player_id", ["4046"]],
    ]);
  });

  it("skips the request entirely when nothing is held", async () => {
    const { client, calls } = createFakeClient({ players: [] });
    expect(await fetchPlayers(client, [])).toEqual([]);
    expect(calls).toHaveLength(0);
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pnpm --filter @ultimate-guillotine/web test src/board/fetchers.test.ts`
Expected: FAIL — `Failed to resolve import "./fetchers"`.

- [ ] **Step 4: Write the fetchers**

Create `apps/web/src/board/fetchers.ts`:

```ts
import type { SupabaseClient } from "@supabase/supabase-js";

import type { Database, TableRow } from "./types";

export type BoardClient = SupabaseClient<Database>;

export type NflStateRow = Pick<
  TableRow<"nfl_state">,
  "id" | "season" | "season_type" | "week" | "display_week" | "synced_at"
>;
export type SeasonRow = TableRow<"seasons">;
export type TeamRow = Pick<
  TableRow<"teams">,
  "id" | "sleeper_roster_id" | "team_name" | "member_id"
>;
export type MemberRow = Pick<
  TableRow<"members">,
  "id" | "sleeper_display_name" | "nickname"
>;
export type TeamSeasonStateRow = TableRow<"team_season_state">;
export type TeamWeekProjectionRow = TableRow<"team_week_projections">;
export type RosterHoldingRow = Pick<
  TableRow<"roster_holdings">,
  "team_id" | "sleeper_player_id" | "slot" | "slot_index" | "lineup_position"
>;
export type PlayerRow = Pick<
  TableRow<"players">,
  "sleeper_player_id" | "full_name" | "position" | "team"
>;
export type PlayerProjectionRow = Pick<
  TableRow<"player_projections">,
  "sleeper_player_id" | "league_points"
>;
export type WeeklyResultFetchRow = Pick<
  TableRow<"weekly_results">,
  "week" | "team_id" | "points" | "is_final" | "state_version"
>;
export type FinalRosterRow = Pick<
  TableRow<"final_rosters">,
  "team_id" | "eliminated_week" | "holdings" | "frozen_at"
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

export async function fetchNflState(client: BoardClient): Promise<NflStateRow | null> {
  const rows = await unwrap<NflStateRow>(
    client
      .from("nfl_state")
      .select("id, season, season_type, week, display_week, synced_at")
      .eq("id", 1),
    "nfl_state",
  );
  return rows[0] ?? null;
}

export async function fetchSeasonByYear(
  client: BoardClient,
  year: number,
): Promise<SeasonRow | null> {
  const rows = await unwrap<SeasonRow>(
    client
      .from("seasons")
      .select(
        "id, year, sleeper_league_id, phase, expected_rosters, waiver_budget, roster_positions, league_synced_at",
      )
      .eq("year", year),
    "seasons",
  );
  return rows[0] ?? null;
}

export function fetchTeams(client: BoardClient, seasonId: number): Promise<TeamRow[]> {
  return unwrap<TeamRow>(
    client
      .from("teams")
      .select("id, sleeper_roster_id, team_name, member_id")
      .eq("season_id", seasonId),
    "teams",
  );
}

export function fetchMembers(client: BoardClient): Promise<MemberRow[]> {
  // The two public label columns only. `display_name` is the bare Sleeper username and is
  // never selected; `private.member_aliases` is never read at all.
  return unwrap<MemberRow>(
    client.from("members").select("id, sleeper_display_name, nickname"),
    "members",
  );
}

export function fetchTeamSeasonState(
  client: BoardClient,
  seasonId: number,
): Promise<TeamSeasonStateRow[]> {
  return unwrap<TeamSeasonStateRow>(
    client
      .from("team_season_state")
      .select(
        "season_id, team_id, faab_budget, faab_used, faab_remaining, wins, losses, ties, points_for, points_against, is_eliminated, eliminated_week, elimination_source, state_version, synced_at",
      )
      .eq("season_id", seasonId),
    "team_season_state",
  );
}

export function fetchTeamWeekProjections(
  client: BoardClient,
  seasonId: number,
  week: number,
): Promise<TeamWeekProjectionRow[]> {
  return unwrap<TeamWeekProjectionRow>(
    client
      .from("team_week_projections")
      .select(
        "season_id, team_id, week, projected_points, starter_slots, filled_slots, empty_slots, starters_projected, missing_projections, coverage_pct, is_provisional, computed_at",
      )
      .eq("season_id", seasonId)
      .eq("week", week),
    "team_week_projections",
  );
}

export function fetchRosterHoldings(
  client: BoardClient,
  seasonId: number,
): Promise<RosterHoldingRow[]> {
  return unwrap<RosterHoldingRow>(
    client
      .from("roster_holdings")
      .select("team_id, sleeper_player_id, slot, slot_index, lineup_position")
      .eq("season_id", seasonId),
    "roster_holdings",
  );
}

export function fetchWeeklyResults(
  client: BoardClient,
  seasonId: number,
): Promise<WeeklyResultFetchRow[]> {
  return unwrap<WeeklyResultFetchRow>(
    client
      .from("weekly_results")
      .select("week, team_id, points, is_final, state_version")
      .eq("season_id", seasonId),
    "weekly_results",
  );
}

/**
 * The frozen snapshots for every eliminated team. Written once at elimination and never
 * updated, so this is a small table — at most one row per team per season.
 */
export function fetchFinalRosters(
  client: BoardClient,
  seasonId: number,
): Promise<FinalRosterRow[]> {
  return unwrap<FinalRosterRow>(
    client
      .from("final_rosters")
      .select("team_id, eliminated_week, holdings, frozen_at")
      .eq("season_id", seasonId),
    "final_rosters",
  );
}

/**
 * One request for every player the board can show — roughly 360 live ids plus whatever the
 * frozen snapshots still name, not one request per team.
 */
export async function fetchPlayers(
  client: BoardClient,
  sleeperPlayerIds: string[],
): Promise<PlayerRow[]> {
  if (sleeperPlayerIds.length === 0) {
    return [];
  }
  return unwrap<PlayerRow>(
    client
      .from("players")
      .select("sleeper_player_id, full_name, position, team")
      .in("sleeper_player_id", sleeperPlayerIds),
    "players",
  );
}

/**
 * player_projections is keyed by the plain season year, not season_id, and is deliberately
 * not in the realtime publication — a run touches thousands of rows.
 */
export async function fetchPlayerProjections(
  client: BoardClient,
  season: number,
  week: number,
  sleeperPlayerIds: string[],
): Promise<PlayerProjectionRow[]> {
  if (sleeperPlayerIds.length === 0) {
    return [];
  }
  return unwrap<PlayerProjectionRow>(
    client
      .from("player_projections")
      .select("sleeper_player_id, league_points")
      .eq("season", season)
      .eq("week", week)
      .in("sleeper_player_id", sleeperPlayerIds),
    "player_projections",
  );
}
```

If TypeScript objects to the `PromiseLike<SupabaseResult<T>>` parameter for a builder, annotate the call site rather than loosening `unwrap` — for example `unwrap<TeamRow>(client.from("teams").select(...).eq(...) as PromiseLike<SupabaseResult<TeamRow>>, "teams")`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `pnpm --filter @ultimate-guillotine/web test src/board/fetchers.test.ts`
Expected: PASS — 13 tests.

- [ ] **Step 6: Write the data hook**

Create `apps/web/src/board/useBoardData.ts`:

```ts
import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { boardClient } from "./boardClient";
import { joinBoardTeams } from "./derive/join";
import {
  fetchFinalRosters,
  fetchMembers,
  fetchNflState,
  fetchPlayerProjections,
  fetchPlayers,
  fetchRosterHoldings,
  fetchSeasonByYear,
  fetchTeamSeasonState,
  fetchTeamWeekProjections,
  fetchTeams,
  fetchWeeklyResults,
} from "./fetchers";
import { boardKeys } from "./queryKeys";
import type { BoardTeam } from "./types";

export interface BoardDataOptions {
  /** false while Realtime is healthy; 60_000 while it is not. */
  pollingMs: number | false;
}

export interface BoardQueryError {
  section: string;
  message: string;
}

export interface BoardDataResult {
  season: number | null;
  week: number | null;
  seasonId: number | null;
  teams: BoardTeam[];
  isPending: boolean;
  isEmpty: boolean;
  errors: BoardQueryError[];
  /**
   * When the projections were last pulled: the newest `team_week_projections.computed_at`
   * for the week. This is what the header shows — not when the browser last refetched.
   */
  projectionsUpdatedAt: number | null;
  refetchAll: () => void;
}

export function useBoardData(options: BoardDataOptions): BoardDataResult {
  const queryClient = useQueryClient();
  const shared = {
    refetchOnWindowFocus: true as const,
    refetchInterval: options.pollingMs,
    staleTime: 15_000,
  };

  const nflState = useQuery({
    queryKey: boardKeys.nflState(),
    queryFn: () => fetchNflState(boardClient),
    ...shared,
  });

  const season = nflState.data?.season ?? null;
  const week = nflState.data?.week ?? null;

  const seasonRow = useQuery({
    queryKey: boardKeys.season(season ?? 0),
    queryFn: () => fetchSeasonByYear(boardClient, season as number),
    enabled: season !== null,
    ...shared,
  });

  const seasonId = seasonRow.data?.id ?? null;
  const hasSeason = seasonId !== null;

  const teams = useQuery({
    queryKey: boardKeys.teams(seasonId ?? 0),
    queryFn: () => fetchTeams(boardClient, seasonId as number),
    enabled: hasSeason,
    ...shared,
  });

  const members = useQuery({
    queryKey: boardKeys.members(),
    queryFn: () => fetchMembers(boardClient),
    ...shared,
  });

  const state = useQuery({
    queryKey: boardKeys.teamSeasonState(seasonId ?? 0),
    queryFn: () => fetchTeamSeasonState(boardClient, seasonId as number),
    enabled: hasSeason,
    ...shared,
  });

  const teamProjections = useQuery({
    queryKey: boardKeys.teamWeekProjections(seasonId ?? 0, week ?? 0),
    queryFn: () =>
      fetchTeamWeekProjections(boardClient, seasonId as number, week as number),
    enabled: hasSeason && week !== null,
    ...shared,
  });

  const holdings = useQuery({
    queryKey: boardKeys.rosterHoldings(seasonId ?? 0),
    queryFn: () => fetchRosterHoldings(boardClient, seasonId as number),
    enabled: hasSeason,
    ...shared,
  });

  const weeklyResults = useQuery({
    queryKey: boardKeys.weeklyResults(seasonId ?? 0),
    queryFn: () => fetchWeeklyResults(boardClient, seasonId as number),
    enabled: hasSeason,
    ...shared,
  });

  const finalRosters = useQuery({
    queryKey: boardKeys.finalRosters(seasonId ?? 0),
    queryFn: () => fetchFinalRosters(boardClient, seasonId as number),
    enabled: hasSeason,
    ...shared,
  });

  // A player frozen onto an eliminated team's snapshot has usually been dropped, so he is no
  // longer in roster_holdings. Both id sets are needed or those rows render as "Unknown player".
  const heldPlayerIds = useMemo(() => {
    const ids = new Set<string>();
    for (const holding of holdings.data ?? []) {
      ids.add(holding.sleeper_player_id);
    }
    for (const snapshot of finalRosters.data ?? []) {
      for (const holding of snapshot.holdings) {
        ids.add(holding.sleeper_player_id);
      }
    }
    return [...ids].sort();
  }, [holdings.data, finalRosters.data]);

  const players = useQuery({
    queryKey: boardKeys.players(seasonId ?? 0),
    queryFn: () => fetchPlayers(boardClient, heldPlayerIds),
    enabled: hasSeason && heldPlayerIds.length > 0,
    ...shared,
  });

  const playerProjections = useQuery({
    queryKey: boardKeys.playerProjections(season ?? 0, week ?? 0),
    queryFn: () =>
      fetchPlayerProjections(
        boardClient,
        season as number,
        week as number,
        heldPlayerIds,
      ),
    enabled: season !== null && week !== null && heldPlayerIds.length > 0,
    ...shared,
  });

  const boardTeams = useMemo(
    () =>
      joinBoardTeams({
        teams: teams.data ?? [],
        members: members.data ?? [],
        teamSeasonState: state.data ?? [],
        teamWeekProjections: teamProjections.data ?? [],
        rosterHoldings: holdings.data ?? [],
        players: players.data ?? [],
        playerProjections: playerProjections.data ?? [],
        weeklyResults: weeklyResults.data ?? [],
        finalRosters: finalRosters.data ?? [],
      }),
    [
      teams.data,
      members.data,
      state.data,
      teamProjections.data,
      holdings.data,
      players.data,
      playerProjections.data,
      weeklyResults.data,
      finalRosters.data,
    ],
  );

  // The last-pull time the header shows: when the projections were computed, not when the
  // browser last refetched them. A refetch that returns identical rows must not look fresher.
  const projectionsUpdatedAt = useMemo(() => {
    let newest: number | null = null;
    for (const row of teamProjections.data ?? []) {
      const computedAt = Date.parse(row.computed_at);
      if (Number.isNaN(computedAt)) {
        continue;
      }
      newest = newest === null ? computedAt : Math.max(newest, computedAt);
    }
    return newest;
  }, [teamProjections.data]);

  const sections: [string, { error: Error | null }][] = [
    ["NFL week", nflState],
    ["Season", seasonRow],
    ["Teams", teams],
    ["Owners", members],
    ["Team state", state],
    ["Projections", teamProjections],
    ["Rosters", holdings],
    ["Players", players],
    ["Player projections", playerProjections],
    ["Weekly results", weeklyResults],
    ["Final rosters", finalRosters],
  ];

  const errors: BoardQueryError[] = sections
    .filter(([, query]) => query.error !== null)
    .map(([section, query]) => ({
      section,
      message: query.error?.message ?? "Unknown error",
    }));

  return {
    season,
    week,
    seasonId,
    teams: boardTeams,
    isPending: nflState.isPending || seasonRow.isPending || teams.isPending,
    isEmpty: !teams.isPending && teams.error === null && boardTeams.length === 0,
    errors,
    projectionsUpdatedAt,
    refetchAll: () => {
      void queryClient.invalidateQueries({ queryKey: boardKeys.all });
    },
  };
}
```

- [ ] **Step 7: Run lint, the full suite, and commit**

```bash
pnpm --filter @ultimate-guillotine/web test
pnpm lint
git add apps/web/src/board/queryKeys.ts apps/web/src/board/fetchers.ts \
  apps/web/src/board/fetchers.test.ts apps/web/src/board/useBoardData.ts
git commit -m "feat: add board query keys, fetchers and data hook"
```

---

### Task 8: The Realtime hook

One channel, four published tables, a 750 ms trailing debounce, the eighteen-event burst ceiling, exponential backoff to 30 s, and a connection flag the header turns into a reconnecting label. Tested with a fake channel and fake timers. The search debounce hook lands here too because it is the same timer machinery.

**Files:**
- Create: `apps/web/src/board/realtime.ts`
- Create: `apps/web/src/board/useLeagueBoardRealtime.ts`
- Create: `apps/web/src/board/useDebouncedValue.ts`
- Test: `apps/web/src/board/realtime.test.ts`
- Test: `apps/web/src/board/useLeagueBoardRealtime.test.tsx`

**Interfaces:**
- Consumes: `boardKeys` from `./queryKeys`; `supabase` from `@/supabaseClient`.
- Produces: from `realtime.ts` — `BOARD_REALTIME_TABLES`, `BoardRealtimeTable`, `REALTIME_DEBOUNCE_MS`, `REALTIME_MAX_EVENTS_PER_BURST`, `REALTIME_BACKOFF_CAP_MS`, `REALTIME_POLL_MS`, `backoffDelayMs(attempt: number): number`, `RealtimeContext`, `keysForTable(table: BoardRealtimeTable, context: RealtimeContext): readonly unknown[][]`; from `useLeagueBoardRealtime.ts` — `FakeableChannel`, `RealtimeTransport`, `UseLeagueBoardRealtimeArgs`, `LeagueBoardRealtime`, `useLeagueBoardRealtime(args): LeagueBoardRealtime`; from `useDebouncedValue.ts` — `useDebouncedValue<T>(value: T, delayMs: number): T`.

- [ ] **Step 1: Write the failing pure-helper test**

Create `apps/web/src/board/realtime.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { boardKeys } from "./queryKeys";
import {
  backoffDelayMs,
  BOARD_REALTIME_TABLES,
  keysForTable,
  REALTIME_DEBOUNCE_MS,
  REALTIME_MAX_EVENTS_PER_BURST,
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
      boardKeys.players(1),
      boardKeys.playerProjections(2026, 3),
    ]);
  });

  it("maps a state change to the state query and the frozen rosters", () => {
    // `final_rosters` is not published, so the elimination that writes a snapshot arrives
    // only as the team_season_state change that flips is_eliminated.
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
      keysForTable("team_week_projections", { seasonId: null, season: null, week: null }),
    ).toEqual([boardKeys.all]);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm --filter @ultimate-guillotine/web test src/board/realtime.test.ts`
Expected: FAIL — `Failed to resolve import "./realtime"`.

- [ ] **Step 3: Write the pure helpers**

Create `apps/web/src/board/realtime.ts`:

```ts
import { boardKeys } from "./queryKeys";

/**
 * Exactly the tables the data layer adds to the supabase_realtime publication.
 * public.player_projections is deliberately not published — a run touches thousands of rows.
 */
export const BOARD_REALTIME_TABLES = [
  "roster_holdings",
  "team_season_state",
  "team_week_projections",
  "nfl_state",
] as const;

export type BoardRealtimeTable = (typeof BOARD_REALTIME_TABLES)[number];

export const REALTIME_DEBOUNCE_MS = 750;
/** Beyond this many events in one window, collapse into a single whole-board refetch. */
export const REALTIME_MAX_EVENTS_PER_BURST = 18;
export const REALTIME_BACKOFF_CAP_MS = 30_000;
export const REALTIME_POLL_MS = 60_000;

export function backoffDelayMs(attempt: number): number {
  return Math.min(REALTIME_BACKOFF_CAP_MS, 1_000 * 2 ** attempt);
}

export interface RealtimeContext {
  seasonId: number | null;
  season: number | null;
  week: number | null;
}

export function keysForTable(
  table: BoardRealtimeTable,
  context: RealtimeContext,
): readonly unknown[][] {
  const { seasonId, season, week } = context;
  if (table === "nfl_state" || seasonId === null || season === null || week === null) {
    return [boardKeys.all as unknown as unknown[]];
  }
  if (table === "team_season_state") {
    // An elimination flips is_eliminated here and writes the final_rosters snapshot in the
    // same transaction, but final_rosters is not in the publication — so pull it from here.
    return [
      boardKeys.teamSeasonState(seasonId) as unknown as unknown[],
      boardKeys.finalRosters(seasonId) as unknown as unknown[],
    ];
  }
  if (table === "team_week_projections") {
    return [boardKeys.teamWeekProjections(seasonId, week) as unknown as unknown[]];
  }
  // A roster change also changes which players and player projections the board needs.
  return [
    boardKeys.rosterHoldings(seasonId) as unknown as unknown[],
    boardKeys.players(seasonId) as unknown as unknown[],
    boardKeys.playerProjections(season, week) as unknown as unknown[],
  ];
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `pnpm --filter @ultimate-guillotine/web test src/board/realtime.test.ts`
Expected: PASS — 7 tests.

- [ ] **Step 5: Write the failing hook test**

Create `apps/web/src/board/useLeagueBoardRealtime.test.tsx`:

```tsx
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { boardKeys } from "./queryKeys";
import type { FakeableChannel, RealtimeTransport } from "./useLeagueBoardRealtime";
import { useLeagueBoardRealtime } from "./useLeagueBoardRealtime";

function createFakeTransport() {
  const handlers = new Map<string, () => void>();
  let statusHandler: ((status: string) => void) | null = null;
  const removeChannel = vi.fn();
  let channelCount = 0;

  const channel: FakeableChannel = {
    on(_event, filter, handler) {
      handlers.set(filter.table, handler);
      return channel;
    },
    subscribe(handler) {
      statusHandler = handler;
      return channel;
    },
  };

  const transport: RealtimeTransport = {
    channel: () => {
      channelCount += 1;
      return channel;
    },
    removeChannel,
  };

  return {
    transport,
    removeChannel,
    emit: (table: string) => handlers.get(table)?.(),
    setStatus: (status: string) => statusHandler?.(status),
    channelCount: () => channelCount,
  };
}

function wrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("useLeagueBoardRealtime", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.useFakeTimers();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    queryClient.clear();
  });

  it("collapses a burst on one table into a single invalidation after the debounce", () => {
    const fake = createFakeTransport();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue();

    renderHook(
      () =>
        useLeagueBoardRealtime({
          seasonId: 1,
          season: 2026,
          week: 3,
          transport: fake.transport,
        }),
      { wrapper: wrapper(queryClient) },
    );

    act(() => {
      fake.setStatus("SUBSCRIBED");
    });
    invalidate.mockClear();

    act(() => {
      fake.emit("team_week_projections");
      fake.emit("team_week_projections");
      fake.emit("team_week_projections");
    });
    expect(invalidate).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(750);
    });
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: boardKeys.teamWeekProjections(1, 3),
    });
  });

  it("invalidates each affected key once per burst", () => {
    const fake = createFakeTransport();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue();

    renderHook(
      () =>
        useLeagueBoardRealtime({
          seasonId: 1,
          season: 2026,
          week: 3,
          transport: fake.transport,
        }),
      { wrapper: wrapper(queryClient) },
    );

    act(() => {
      fake.setStatus("SUBSCRIBED");
    });
    invalidate.mockClear();

    act(() => {
      fake.emit("team_season_state");
      fake.emit("team_week_projections");
      fake.emit("team_season_state");
      vi.advanceTimersByTime(750);
    });

    expect(invalidate).toHaveBeenCalledTimes(2);
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: boardKeys.teamSeasonState(1),
    });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: boardKeys.teamWeekProjections(1, 3),
    });
  });

  it("collapses to one whole-board refetch past the eighteen-event ceiling", () => {
    const fake = createFakeTransport();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue();

    renderHook(
      () =>
        useLeagueBoardRealtime({
          seasonId: 1,
          season: 2026,
          week: 3,
          transport: fake.transport,
        }),
      { wrapper: wrapper(queryClient) },
    );

    act(() => {
      fake.setStatus("SUBSCRIBED");
    });
    invalidate.mockClear();

    act(() => {
      for (let index = 0; index < 25; index += 1) {
        fake.emit("roster_holdings");
      }
      vi.advanceTimersByTime(750);
    });

    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: boardKeys.all });
  });

  it("reports the connection state and refetches everything on reconnect", () => {
    const fake = createFakeTransport();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue();

    const { result } = renderHook(
      () =>
        useLeagueBoardRealtime({
          seasonId: 1,
          season: 2026,
          week: 3,
          transport: fake.transport,
        }),
      { wrapper: wrapper(queryClient) },
    );

    expect(result.current.isConnected).toBe(false);

    act(() => {
      fake.setStatus("SUBSCRIBED");
    });
    expect(result.current.isConnected).toBe(true);

    act(() => {
      fake.setStatus("CHANNEL_ERROR");
    });
    expect(result.current.isConnected).toBe(false);
    expect(result.current.reconnectAttempts).toBe(0);

    invalidate.mockClear();
    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    expect(fake.channelCount()).toBe(2);
    expect(result.current.reconnectAttempts).toBe(1);

    act(() => {
      fake.setStatus("SUBSCRIBED");
    });
    // Changes during the gap were missed, so everything refetches.
    expect(invalidate).toHaveBeenCalledWith({ queryKey: boardKeys.all });
    expect(result.current.reconnectAttempts).toBe(0);
  });

  it("notifies the caller when the connection state changes", () => {
    const fake = createFakeTransport();
    const onConnectionChange = vi.fn();

    renderHook(
      () =>
        useLeagueBoardRealtime({
          seasonId: 1,
          season: 2026,
          week: 3,
          transport: fake.transport,
          onConnectionChange,
        }),
      { wrapper: wrapper(queryClient) },
    );

    act(() => {
      fake.setStatus("SUBSCRIBED");
    });
    expect(onConnectionChange).toHaveBeenCalledWith(true);

    act(() => {
      fake.setStatus("CLOSED");
    });
    expect(onConnectionChange).toHaveBeenLastCalledWith(false);
  });

  it("removes the channel on unmount", () => {
    const fake = createFakeTransport();
    const { unmount } = renderHook(
      () =>
        useLeagueBoardRealtime({
          seasonId: 1,
          season: 2026,
          week: 3,
          transport: fake.transport,
        }),
      { wrapper: wrapper(queryClient) },
    );

    unmount();
    expect(fake.removeChannel).toHaveBeenCalled();
  });
});
```

- [ ] **Step 6: Run it to verify it fails**

Run: `pnpm --filter @ultimate-guillotine/web test src/board/useLeagueBoardRealtime.test.tsx`
Expected: FAIL — `Failed to resolve import "./useLeagueBoardRealtime"`.

- [ ] **Step 7: Write the hook**

Create `apps/web/src/board/useLeagueBoardRealtime.ts`:

```ts
import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { supabase } from "@/supabaseClient";

import { boardKeys } from "./queryKeys";
import {
  backoffDelayMs,
  BOARD_REALTIME_TABLES,
  type BoardRealtimeTable,
  keysForTable,
  REALTIME_DEBOUNCE_MS,
  REALTIME_MAX_EVENTS_PER_BURST,
} from "./realtime";

/** The slice of a Supabase RealtimeChannel the board uses, so tests can supply a fake. */
export interface FakeableChannel {
  on(
    event: "postgres_changes",
    filter: { event: "*"; schema: "public"; table: string },
    handler: () => void,
  ): FakeableChannel;
  subscribe(handler: (status: string) => void): FakeableChannel;
}

export interface RealtimeTransport {
  channel(name: string): FakeableChannel;
  removeChannel(channel: FakeableChannel): void;
}

export interface UseLeagueBoardRealtimeArgs {
  seasonId: number | null;
  season: number | null;
  week: number | null;
  transport?: RealtimeTransport;
  onConnectionChange?: (isConnected: boolean) => void;
}

export interface LeagueBoardRealtime {
  isConnected: boolean;
  reconnectAttempts: number;
  refreshNow: () => void;
}

const defaultTransport: RealtimeTransport = {
  channel: (name) => supabase.channel(name) as unknown as FakeableChannel,
  removeChannel: (channel) => {
    void supabase.removeChannel(channel as never);
  },
};

export function useLeagueBoardRealtime(
  args: UseLeagueBoardRealtimeArgs,
): LeagueBoardRealtime {
  const { seasonId, season, week, transport, onConnectionChange } = args;
  const queryClient = useQueryClient();

  const [isConnected, setIsConnected] = useState(false);
  const [reconnectAttempts, setReconnectAttempts] = useState(0);

  const contextRef = useRef({ seasonId, season, week });
  contextRef.current = { seasonId, season, week };

  const onConnectionChangeRef = useRef(onConnectionChange);
  onConnectionChangeRef.current = onConnectionChange;

  const pendingTablesRef = useRef(new Set<BoardRealtimeTable>());
  const burstEventCountRef = useRef(0);
  const flushTimerRef = useRef<number | null>(null);

  const refreshNow = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: boardKeys.all });
  }, [queryClient]);

  const flush = useCallback(() => {
    flushTimerRef.current = null;
    const tables = [...pendingTablesRef.current];
    const eventCount = burstEventCountRef.current;
    pendingTablesRef.current = new Set();
    burstEventCountRef.current = 0;

    if (tables.length === 0) {
      return;
    }
    // Past the ceiling, one whole-board refetch is cheaper than a key-by-key storm.
    if (eventCount > REALTIME_MAX_EVENTS_PER_BURST) {
      void queryClient.invalidateQueries({ queryKey: boardKeys.all });
      return;
    }

    const seen = new Set<string>();
    for (const table of tables) {
      for (const queryKey of keysForTable(table, contextRef.current)) {
        const fingerprint = JSON.stringify(queryKey);
        if (seen.has(fingerprint)) {
          continue;
        }
        seen.add(fingerprint);
        void queryClient.invalidateQueries({ queryKey });
      }
    }
  }, [queryClient]);

  const enqueue = useCallback(
    (table: BoardRealtimeTable) => {
      pendingTablesRef.current.add(table);
      burstEventCountRef.current += 1;
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current);
      }
      flushTimerRef.current = window.setTimeout(flush, REALTIME_DEBOUNCE_MS);
    },
    [flush],
  );

  useEffect(() => {
    const active = transport ?? defaultTransport;
    let retryTimer: number | null = null;
    let cancelled = false;

    const channel = active.channel(`league-board-${reconnectAttempts}`);
    for (const table of BOARD_REALTIME_TABLES) {
      channel.on("postgres_changes", { event: "*", schema: "public", table }, () => {
        enqueue(table);
      });
    }

    channel.subscribe((status) => {
      if (cancelled) {
        return;
      }
      if (status === "SUBSCRIBED") {
        setIsConnected(true);
        setReconnectAttempts(0);
        onConnectionChangeRef.current?.(true);
        // Anything that changed while the channel was down was missed.
        void queryClient.invalidateQueries({ queryKey: boardKeys.all });
        return;
      }
      if (status === "CHANNEL_ERROR" || status === "TIMED_OUT" || status === "CLOSED") {
        setIsConnected(false);
        onConnectionChangeRef.current?.(false);
        if (retryTimer === null) {
          retryTimer = window.setTimeout(() => {
            retryTimer = null;
            setReconnectAttempts((attempt) => attempt + 1);
          }, backoffDelayMs(reconnectAttempts));
        }
      }
    });

    return () => {
      cancelled = true;
      if (retryTimer !== null) {
        window.clearTimeout(retryTimer);
      }
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
      active.removeChannel(channel);
    };
  }, [enqueue, queryClient, reconnectAttempts, transport]);

  return { isConnected, reconnectAttempts, refreshNow };
}
```

- [ ] **Step 8: Write the search debounce hook**

Create `apps/web/src/board/useDebouncedValue.ts`:

```ts
import { useEffect, useState } from "react";

/** Keeps typing in the search field from re-deriving the board on every keystroke. */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `pnpm --filter @ultimate-guillotine/web test src/board`
Expected: PASS — 6 hook tests plus everything from Tasks 1–7.

- [ ] **Step 10: Run lint and commit**

```bash
pnpm lint
git add apps/web/src/board/realtime.ts apps/web/src/board/realtime.test.ts \
  apps/web/src/board/useLeagueBoardRealtime.ts \
  apps/web/src/board/useLeagueBoardRealtime.test.tsx \
  apps/web/src/board/useDebouncedValue.ts
git commit -m "feat: add board realtime subscription with debounced invalidation"
```

---

### Task 9: Team card and roster panel

The mobile-first card and its expandable roster, built from the shadcn primitives already vendored in `src/components/ui/` (`card.tsx`, `badge.tsx`, `collapsible.tsx`), plus the reduced-motion rule. Per Ben's decision 3 an eliminated card stays expandable, carries an `Eliminated week N` label, and its panel says the roster is the frozen one.

**Files:**
- Create: `apps/web/src/board/components/RosterPanel.tsx`
- Create: `apps/web/src/board/components/TeamCard.tsx`
- Modify: `apps/web/src/globals.css` (append the reduced-motion block)
- Test: `apps/web/src/board/components/TeamCard.test.tsx`

**Interfaces:**
- Consumes: `BoardTeam`, `RosterPlayer` from `../types`; `resolveProjectionDisplay` from `../derive/projection`; `groupRosterBySlot` from `../derive/roster`; `Card`, `CardContent` from `@/components/ui/card`; `Badge` from `@/components/ui/badge`; `Collapsible`, `CollapsibleContent` from `@/components/ui/collapsible`; `cn` from `@/lib/utils`.
- Produces: `RosterPanel({ players, highlightedPlayerIds })`, `TeamCard({ team, rank, isOpen, onToggle, highlightedPlayerIds })`.

- [ ] **Step 1: Write the failing test**

Create `apps/web/src/board/components/TeamCard.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BoardTeam, RosterPlayer } from "../types";
import { TeamCard } from "./TeamCard";

const player = (over: Partial<RosterPlayer> & { sleeperPlayerId: string }): RosterPlayer => ({
  fullName: "Patrick Mahomes",
  position: "QB",
  nflTeam: "KC",
  slot: "starter",
  slotIndex: 0,
  lineupPosition: "QB",
  projectedPoints: 22.6,
  ...over,
});

const team = (over: Partial<BoardTeam> = {}): BoardTeam => ({
  isRosterFrozen: false,
  teamId: 7,
  teamName: "The Choppers",
  ownerName: "benray",
  sleeperRosterId: 1,
  projectedPoints: 112.4,
  coveragePct: 100,
  isProvisional: false,
  projectionComputedAt: "2026-09-09T12:00:00Z",
  faabRemaining: 75,
  wins: 2,
  losses: 1,
  ties: 0,
  pointsFor: 301.5,
  isEliminated: false,
  eliminatedWeek: null,
  eliminationSource: null,
  roster: [player({ sleeperPlayerId: "4046" })],
  ...over,
});

const noop = () => undefined;
const noHighlights = new Set<string>();

describe("TeamCard", () => {
  it("shows owner, team, projection, FAAB and record", () => {
    render(
      <ul>
        <TeamCard team={team()} rank={1} isOpen={false} onToggle={noop} highlightedPlayerIds={noHighlights} />
      </ul>,
    );
    expect(screen.getByText("benray")).toBeInTheDocument();
    expect(screen.getByText("The Choppers")).toBeInTheDocument();
    expect(screen.getByText("112.4")).toBeInTheDocument();
    expect(screen.getByText(/\$75 FAAB/)).toBeInTheDocument();
    expect(screen.getByText(/2-1/)).toBeInTheDocument();
    expect(screen.getByText(/301\.5 PF/)).toBeInTheDocument();
  });

  it("wires the toggle button to the roster panel", () => {
    const onToggle = vi.fn();
    render(
      <ul>
        <TeamCard team={team()} rank={1} isOpen={false} onToggle={onToggle} highlightedPlayerIds={noHighlights} />
      </ul>,
    );
    const toggle = screen.getByRole("button", { name: /benray/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle.getAttribute("aria-controls")).toBeTruthy();
    fireEvent.click(toggle);
    expect(onToggle).toHaveBeenCalledWith(7);
  });

  it("renders the roster with a starters heading when open", () => {
    render(
      <ul>
        <TeamCard team={team()} rank={1} isOpen onToggle={noop} highlightedPlayerIds={noHighlights} />
      </ul>,
    );
    expect(screen.getByRole("button", { name: /benray/i })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Starters")).toBeInTheDocument();
    expect(screen.getByText("Patrick Mahomes")).toBeInTheDocument();
    expect(screen.getByText("QB · KC")).toBeInTheDocument();
    expect(screen.getByText("22.6")).toBeInTheDocument();
  });

  it("renders an em dash and a caveat instead of a zero when the projection is missing", () => {
    render(
      <ul>
        <TeamCard
          team={team({ projectedPoints: null, coveragePct: null, isProvisional: true })}
          rank={1}
          isOpen={false}
          onToggle={noop}
          highlightedPlayerIds={noHighlights}
        />
      </ul>,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("Projection unavailable")).toBeInTheDocument();
    expect(screen.queryByText("0.0")).not.toBeInTheDocument();
  });

  it("badges partial coverage without hiding the number", () => {
    render(
      <ul>
        <TeamCard
          team={team({ projectedPoints: 80, coveragePct: 66.7, isProvisional: true })}
          rank={1}
          isOpen={false}
          onToggle={noop}
          highlightedPlayerIds={noHighlights}
        />
      </ul>,
    );
    expect(screen.getByText("80.0")).toBeInTheDocument();
    expect(screen.getByText("Partial projection coverage")).toBeInTheDocument();
  });

  it("dims an eliminated team and labels the week plainly", () => {
    const { container } = render(
      <ul>
        <TeamCard
          team={team({ isEliminated: true, eliminatedWeek: 4, eliminationSource: "sleeper_inferred" })}
          rank={1}
          isOpen={false}
          onToggle={noop}
          highlightedPlayerIds={noHighlights}
        />
      </ul>,
    );
    const label = screen.getByText("Eliminated week 4");
    expect(label).toBeInTheDocument();
    // A provisional ruling is a tooltip, not extra label text.
    expect(label).toHaveAttribute("title", expect.stringContaining("Provisional"));
    expect(container.querySelector(".opacity-60")).not.toBeNull();
  });

  it("stays expandable when eliminated and shows the frozen roster", () => {
    render(
      <ul>
        <TeamCard
          team={team({
            isEliminated: true,
            eliminatedWeek: 4,
            eliminationSource: "adjudicator",
            isRosterFrozen: true,
          })}
          rank={1}
          isOpen
          onToggle={noop}
          highlightedPlayerIds={noHighlights}
        />
      </ul>,
    );
    expect(screen.getByRole("button", { name: /benray/i })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText("Final roster, frozen at elimination")).toBeInTheDocument();
    expect(screen.getByText("Patrick Mahomes")).toBeInTheDocument();
    expect(screen.getByText("Eliminated week 4")).not.toHaveAttribute("title");
  });

  it("shows an em dash for a player with no projection", () => {
    render(
      <ul>
        <TeamCard
          team={team({ roster: [player({ sleeperPlayerId: "9", fullName: "Nobody", projectedPoints: null })] })}
          rank={1}
          isOpen
          onToggle={noop}
          highlightedPlayerIds={noHighlights}
        />
      </ul>,
    );
    expect(screen.getByText("Nobody")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm --filter @ultimate-guillotine/web test src/board/components/TeamCard.test.tsx`
Expected: FAIL — `Failed to resolve import "./TeamCard"`.

- [ ] **Step 3: Write the roster panel**

Create `apps/web/src/board/components/RosterPanel.tsx`:

```tsx
import { memo } from "react";

import { cn } from "@/lib/utils";

import { groupRosterBySlot } from "../derive/roster";
import type { RosterPlayer } from "../types";

interface PlayerRowProps {
  player: RosterPlayer;
  isHighlighted: boolean;
}

const PlayerRow = memo(function PlayerRow({ player, isHighlighted }: PlayerRowProps) {
  const meta = [player.position, player.nflTeam].filter(Boolean).join(" · ");
  return (
    <li
      className={cn(
        "flex items-baseline justify-between gap-2 py-0.5 text-sm",
        isHighlighted && "rounded bg-accent px-1 text-accent-foreground",
      )}
    >
      <span className="min-w-0 truncate">
        <span className="font-medium">{player.fullName}</span>
        {meta === "" ? null : (
          <span className="ml-2 text-muted-foreground">{meta}</span>
        )}
      </span>
      <span className="shrink-0 tabular-nums text-muted-foreground">
        {player.projectedPoints === null ? "—" : player.projectedPoints.toFixed(1)}
      </span>
    </li>
  );
});

interface RosterPanelProps {
  players: RosterPlayer[];
  highlightedPlayerIds: ReadonlySet<string>;
}

export function RosterPanel({ players, highlightedPlayerIds }: RosterPanelProps) {
  if (players.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No roster rows yet — waiting for the first sync.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {groupRosterBySlot(players).map((group) => (
        <div key={group.slot}>
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {group.label}
          </h4>
          <ul>
            {group.players.map((player) => (
              <PlayerRow
                key={player.sleeperPlayerId}
                player={player}
                isHighlighted={highlightedPlayerIds.has(player.sleeperPlayerId)}
              />
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Write the team card**

Create `apps/web/src/board/components/TeamCard.tsx`. Badges sit outside the `<button>` because `Badge` renders a `<div>` and a `<div>` inside a `<button>` is invalid HTML.

```tsx
import { memo, useId } from "react";
import { ChevronDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

import { resolveProjectionDisplay } from "../derive/projection";
import type { BoardTeam } from "../types";
import { RosterPanel } from "./RosterPanel";

interface TeamCardProps {
  team: BoardTeam;
  rank: number;
  isOpen: boolean;
  onToggle: (teamId: number) => void;
  highlightedPlayerIds: ReadonlySet<string>;
}

export const TeamCard = memo(function TeamCard({
  team,
  rank,
  isOpen,
  onToggle,
  highlightedPlayerIds,
}: TeamCardProps) {
  const panelId = useId();
  const projection = resolveProjectionDisplay(team);
  const record = `${team.wins}-${team.losses}${team.ties > 0 ? `-${team.ties}` : ""}`;
  const faab = team.faabRemaining === null ? "FAAB —" : `$${team.faabRemaining} FAAB`;

  return (
    <li>
      <Card className={cn("overflow-hidden", team.isEliminated && "opacity-60")}>
        <Collapsible open={isOpen}>
          <button
            type="button"
            aria-expanded={isOpen}
            aria-controls={panelId}
            onClick={() => onToggle(team.teamId)}
            className="flex w-full items-start gap-3 p-4 text-left"
          >
            <span className="w-5 shrink-0 pt-1 text-sm tabular-nums text-muted-foreground">
              {rank}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{team.ownerName}</span>
              <span className="block truncate text-sm text-muted-foreground">
                {team.teamName}
              </span>
              <span className="mt-1 block text-xs text-muted-foreground">
                {record} · {team.pointsFor.toFixed(1)} PF · {faab}
              </span>
            </span>
            <span className="shrink-0 text-right">
              <span className="block text-2xl font-semibold tabular-nums">
                {projection.text}
              </span>
              <span className="block text-xs text-muted-foreground">proj</span>
            </span>
            <ChevronDown
              aria-hidden="true"
              className={cn(
                "mt-1 h-4 w-4 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none",
                isOpen && "rotate-180",
              )}
            />
          </button>

          {projection.caveatLabel !== null || team.isEliminated ? (
            <div className="flex flex-wrap gap-2 px-4 pb-3">
              {projection.caveatLabel === null ? null : (
                <Badge
                  variant="outline"
                  title={
                    team.projectionComputedAt === null
                      ? undefined
                      : `Computed ${team.projectionComputedAt}`
                  }
                >
                  {projection.caveatLabel}
                </Badge>
              )}
              {team.isEliminated ? (
                <Badge
                  variant="secondary"
                  title={
                    team.eliminationSource === "sleeper_inferred"
                      ? "Provisional: inferred from Sleeper, not yet ruled by the Adjudicator"
                      : undefined
                  }
                >
                  {team.eliminatedWeek === null
                    ? "Eliminated"
                    : `Eliminated week ${team.eliminatedWeek}`}
                </Badge>
              ) : null}
            </div>
          ) : null}

          <CollapsibleContent id={panelId} forceMount={isOpen ? true : undefined} hidden={!isOpen}>
            <CardContent className="border-t pt-4">
              {team.isRosterFrozen ? (
                <p className="mb-2 text-xs text-muted-foreground">
                  Final roster, frozen at elimination
                </p>
              ) : null}
              <RosterPanel
                players={team.roster}
                highlightedPlayerIds={highlightedPlayerIds}
              />
            </CardContent>
          </CollapsibleContent>
        </Collapsible>
      </Card>
    </li>
  );
});
```

- [ ] **Step 5: Add the reduced-motion rule**

Append to the end of `apps/web/src/globals.css`:

```css
@media (prefers-reduced-motion: reduce) {
  [data-radix-collapsible-content],
  [data-state="open"],
  [data-state="closed"] {
    animation: none !important;
    transition: none !important;
  }
}
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `pnpm --filter @ultimate-guillotine/web test src/board/components/TeamCard.test.tsx`
Expected: PASS — 8 tests.

- [ ] **Step 7: Run lint and commit**

```bash
pnpm lint
git add apps/web/src/board/components/RosterPanel.tsx \
  apps/web/src/board/components/TeamCard.tsx \
  apps/web/src/board/components/TeamCard.test.tsx apps/web/src/globals.css
git commit -m "feat: add board team card and roster panel"
```

---

### Task 10: Header, states, page assembly, the home route and the layout

The sticky header (week, sort toggles, search, last-pull indicator), the empty/stale/error/disconnected states, the page that wires everything together plus its one-line `Projections: Sleeper` footer, the board served at `/` with `board` kept only as a redirect, and the stripped-down layout that holds nothing but the title and the theme toggle.

**Files:**
- Create: `apps/web/src/board/components/BoardStates.tsx`
- Create: `apps/web/src/board/components/BoardHeader.tsx`
- Create: `apps/web/src/app/board/BoardPage.tsx`
- Modify: `apps/web/src/router.tsx`
- Modify: `apps/web/src/app/layout.tsx`
- Test: `apps/web/src/app/board/BoardPage.test.tsx`

**Interfaces:**
- Consumes: `useBoardData` from `@/board/useBoardData`; `useLeagueBoardRealtime` from `@/board/useLeagueBoardRealtime`; `REALTIME_POLL_MS` from `@/board/realtime`; `useDebouncedValue` from `@/board/useDebouncedValue`; `sortBoardTeams`, `selectEffectiveSortMode` from `@/board/derive/sort`; `filterTeams` from `@/board/derive/search`; `formatUpdatedAt`, `formatUpdatedAgo`, `isStale`, `crossesMinuteBoundary` from `@/board/derive/time`; `parseSortMode`, `SORT_MODES`, `SORT_MODE_LABELS` from `@/board/types`; `TeamCard` from `@/board/components/TeamCard`; `ModeToggle` from `@/components/mode-toggle`; `Alert`, `AlertDescription`, `AlertTitle`, `Badge`, `Button`, `Input`, `Skeleton`, `ToggleGroup`, `ToggleGroupItem` from `@/components/ui/*`.
- Produces: `BoardSkeleton`, `BoardEmpty`, `BoardErrors`, `RealtimeBanner`, `EliminatedDivider` from `BoardStates.tsx`; `BoardHeader` from `BoardHeader.tsx`; `BoardPage` from `BoardPage.tsx`; the board at `/` and the `board` → `/` redirect.

- [ ] **Step 1: Write the state components**

Create `apps/web/src/board/components/BoardStates.tsx`:

```tsx
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

import type { BoardQueryError } from "../useBoardData";

export function BoardSkeleton() {
  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }, (_, index) => index).map((index) => (
        <li key={index}>
          <Card>
            <CardContent className="space-y-2 p-4">
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-3 w-2/3" />
              <Skeleton className="h-3 w-1/3" />
            </CardContent>
          </Card>
        </li>
      ))}
    </ul>
  );
}

export function BoardEmpty() {
  return (
    <Card>
      <CardContent className="p-6">
        <p className="font-medium">Waiting for the first sync</p>
        <p className="mt-1 text-sm text-muted-foreground">
          No teams have been written to Supabase yet. The board fills in as soon as the
          sync job runs.
        </p>
      </CardContent>
    </Card>
  );
}

export function BoardErrors({
  errors,
  onRetry,
}: {
  errors: BoardQueryError[];
  onRetry: () => void;
}) {
  if (errors.length === 0) {
    return null;
  }
  return (
    <div className="space-y-2">
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
    </div>
  );
}

export function RealtimeBanner({ onRefresh }: { onRefresh: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border bg-muted/50 px-3 py-2 text-sm text-muted-foreground">
      <span>Live updates are paused. Polling every 60 seconds.</span>
      <Button size="sm" variant="outline" onClick={onRefresh}>
        Refresh now
      </Button>
    </div>
  );
}

export function EliminatedDivider({ count }: { count: number }) {
  return (
    <h2 className="mt-6 border-t pt-4 text-sm font-semibold text-muted-foreground">
      Eliminated ({count})
    </h2>
  );
}
```

- [ ] **Step 2: Write the header**

Create `apps/web/src/board/components/BoardHeader.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

import {
  crossesMinuteBoundary,
  formatUpdatedAgo,
  formatUpdatedAt,
  isStale,
} from "../derive/time";
import { SORT_MODE_LABELS, SORT_MODES, type SortMode } from "../types";

interface BoardHeaderProps {
  week: number | null;
  sortMode: SortMode;
  onSortModeChange: (mode: SortMode) => void;
  sortFellBack: boolean;
  searchTerm: string;
  onSearchTermChange: (term: string) => void;
  /** When the projections were pulled — `team_week_projections.computed_at`. */
  projectionsUpdatedAt: number | null;
  isRealtimeConnected: boolean;
}

export function BoardHeader({
  week,
  sortMode,
  onSortModeChange,
  sortFellBack,
  searchTerm,
  onSearchTermChange,
  projectionsUpdatedAt,
  isRealtimeConnected,
}: BoardHeaderProps) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  // The indicator ticks every second but only announces on a minute boundary.
  const [announced, setAnnounced] = useState("");
  const previousElapsedRef = useRef(0);
  const elapsed =
    projectionsUpdatedAt === null ? 0 : Math.max(0, now - projectionsUpdatedAt);
  useEffect(() => {
    if (crossesMinuteBoundary(previousElapsedRef.current, elapsed)) {
      setAnnounced(
        `${formatUpdatedAt(projectionsUpdatedAt, now)}, ${formatUpdatedAgo(projectionsUpdatedAt, now)}`,
      );
    }
    previousElapsedRef.current = elapsed;
  }, [elapsed, projectionsUpdatedAt, now]);

  const stale = isStale(projectionsUpdatedAt, now);

  return (
    <header className="sticky top-0 z-20 -mx-4 mb-3 space-y-2 border-b bg-background/95 px-4 py-3 backdrop-blur sm:mx-0 sm:px-0">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        {/* The site title lives in the layout; this header names the week only. */}
        <h2 className="text-lg font-semibold">
          {week === null ? "Week —" : `Week ${week}`}
        </h2>
        {/*
          Ben's decision 2: the absolute pull time in the viewer's own timezone leads, the
          relative form follows as smaller secondary text, and no provider wording appears
          here at all — the provider is named once in the page footer.
        */}
        <span className="text-sm text-muted-foreground" aria-hidden="true">
          {formatUpdatedAt(projectionsUpdatedAt, now)}
        </span>
        <span className="text-xs text-muted-foreground/80" aria-hidden="true">
          {formatUpdatedAgo(projectionsUpdatedAt, now)}
        </span>
        {stale ? <Badge variant="outline">Stale data</Badge> : null}
        {!isRealtimeConnected ? (
          <span className="text-xs text-muted-foreground">reconnecting</span>
        ) : null}
      </div>

      <p className="sr-only" aria-live="polite">
        {announced}
      </p>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <ToggleGroup
          type="single"
          value={sortMode}
          onValueChange={(value) => {
            if (value !== "") {
              onSortModeChange(value as SortMode);
            }
          }}
          aria-label="Sort teams by"
          variant="outline"
          size="sm"
        >
          {SORT_MODES.map((mode) => (
            <ToggleGroupItem key={mode} value={mode} aria-label={SORT_MODE_LABELS[mode]}>
              {SORT_MODE_LABELS[mode]}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>

        <Input
          type="search"
          value={searchTerm}
          onChange={(event) => onSearchTermChange(event.target.value)}
          placeholder="Search owner, team, or player"
          aria-label="Search owner, team, or player"
          className="sm:max-w-xs"
        />
      </div>

      {sortFellBack ? (
        <p className="text-xs text-muted-foreground">
          No projections available, so teams are sorted by points for.
        </p>
      ) : null}
    </header>
  );
}
```

- [ ] **Step 3: Write the failing page test**

Create `apps/web/src/app/board/BoardPage.test.tsx`. `useBoardData` and `useLeagueBoardRealtime` are mocked so the page's own wiring — sorting, grouping, search, states — is what gets exercised.

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BoardTeam } from "@/board/types";
import type { BoardDataResult } from "@/board/useBoardData";

const boardData = vi.hoisted(() => ({ current: null as BoardDataResult | null }));
const realtime = vi.hoisted(() => ({ isConnected: true }));

vi.mock("@/board/useBoardData", () => ({
  useBoardData: () => boardData.current,
}));

vi.mock("@/board/useLeagueBoardRealtime", () => ({
  useLeagueBoardRealtime: () => ({
    isConnected: realtime.isConnected,
    reconnectAttempts: 0,
    refreshNow: vi.fn(),
  }),
}));

import { BoardPage } from "./BoardPage";

const team = (over: Partial<BoardTeam> & { teamId: number }): BoardTeam => ({
  isRosterFrozen: false,
  teamName: `Team ${over.teamId}`,
  ownerName: `owner${over.teamId}`,
  sleeperRosterId: over.teamId,
  projectedPoints: 100,
  coveragePct: 100,
  isProvisional: false,
  projectionComputedAt: "2026-09-09T12:00:00Z",
  faabRemaining: 50,
  wins: 1,
  losses: 0,
  ties: 0,
  pointsFor: 100,
  isEliminated: false,
  eliminatedWeek: null,
  eliminationSource: null,
  roster: [],
  ...over,
});

const result = (over: Partial<BoardDataResult> = {}): BoardDataResult => ({
  season: 2026,
  week: 3,
  seasonId: 1,
  teams: [],
  isPending: false,
  isEmpty: false,
  errors: [],
  projectionsUpdatedAt: Date.now(),
  refetchAll: vi.fn(),
  ...over,
});

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/"]}>
        <BoardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BoardPage", () => {
  beforeEach(() => {
    realtime.isConnected = true;
    boardData.current = result();
  });

  it("shows skeletons while pending", () => {
    boardData.current = result({ isPending: true });
    const { container } = renderPage();
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("shows the waiting card when there are no rows", () => {
    boardData.current = result({ isEmpty: true });
    renderPage();
    expect(screen.getByText("Waiting for the first sync")).toBeInTheDocument();
  });

  it("names the failing section and keeps showing the rest of the board", () => {
    boardData.current = result({
      teams: [team({ teamId: 1 })],
      errors: [{ section: "Projections", message: "network down" }],
    });
    renderPage();
    expect(screen.getByText("Projections could not load")).toBeInTheDocument();
    expect(screen.getByText("owner1")).toBeInTheDocument();
  });

  it("renders teams in projection order inside a list", () => {
    boardData.current = result({
      teams: [
        team({ teamId: 1, projectedPoints: 90 }),
        team({ teamId: 2, projectedPoints: 140 }),
      ],
    });
    renderPage();
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("owner2");
    expect(items[1]).toHaveTextContent("owner1");
  });

  it("groups eliminated teams under a divider", () => {
    boardData.current = result({
      teams: [
        team({ teamId: 1, projectedPoints: 10 }),
        team({ teamId: 2, projectedPoints: 200, isEliminated: true, eliminatedWeek: 2 }),
      ],
    });
    renderPage();
    expect(screen.getByText("Eliminated (1)")).toBeInTheDocument();
  });

  it("names the provider exactly once, in the footer", () => {
    boardData.current = result({ teams: [team({ teamId: 1 })] });
    renderPage();
    expect(screen.getByText("Projections: Sleeper")).toBeInTheDocument();
    expect(screen.queryByText(/Projections from Sleeper/)).not.toBeInTheDocument();
  });

  it("leads the last-pull indicator with an absolute local time", () => {
    boardData.current = result({ teams: [team({ teamId: 1 })] });
    renderPage();
    expect(screen.getByText(/^Updated /)).toBeInTheDocument();
  });

  it("shows the paused banner when realtime is down", () => {
    realtime.isConnected = false;
    boardData.current = result({ teams: [team({ teamId: 1 })] });
    renderPage();
    expect(
      screen.getByText("Live updates are paused. Polling every 60 seconds."),
    ).toBeInTheDocument();
  });

  it("filters teams as the search term settles", async () => {
    boardData.current = result({
      teams: [team({ teamId: 1 }), team({ teamId: 2, ownerName: "charlie" })],
    });
    renderPage();
    fireEvent.change(screen.getByLabelText("Search owner, team, or player"), {
      target: { value: "charlie" },
    });
    await waitFor(() => {
      expect(screen.queryByText("owner1")).not.toBeInTheDocument();
    });
    expect(screen.getByText("charlie")).toBeInTheDocument();
  });

  it("changes the sort and records it in the URL", async () => {
    boardData.current = result({
      teams: [
        team({ teamId: 1, projectedPoints: 200, faabRemaining: 1 }),
        team({ teamId: 2, projectedPoints: 10, faabRemaining: 99 }),
      ],
    });
    renderPage();
    fireEvent.click(screen.getByRole("radio", { name: "FAAB" }));
    await waitFor(() => {
      expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("owner2");
    });
  });

  it("says when the sort fell back because no projection is usable", () => {
    boardData.current = result({
      teams: [team({ teamId: 1, projectedPoints: null, coveragePct: null, isProvisional: true })],
    });
    renderPage();
    expect(
      screen.getByText("No projections available, so teams are sorted by points for."),
    ).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `pnpm --filter @ultimate-guillotine/web test src/app/board/BoardPage.test.tsx`
Expected: FAIL — `Failed to resolve import "./BoardPage"`.

- [ ] **Step 5: Write the page**

Create `apps/web/src/app/board/BoardPage.tsx`:

```tsx
import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { BoardHeader } from "@/board/components/BoardHeader";
import {
  BoardEmpty,
  BoardErrors,
  BoardSkeleton,
  EliminatedDivider,
  RealtimeBanner,
} from "@/board/components/BoardStates";
import { TeamCard } from "@/board/components/TeamCard";
import { filterTeams } from "@/board/derive/search";
import { selectEffectiveSortMode, sortBoardTeams } from "@/board/derive/sort";
import { REALTIME_POLL_MS } from "@/board/realtime";
import { parseSortMode, type SortMode } from "@/board/types";
import { useBoardData } from "@/board/useBoardData";
import { useDebouncedValue } from "@/board/useDebouncedValue";
import { useLeagueBoardRealtime } from "@/board/useLeagueBoardRealtime";

const GRID = "grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3";

export function BoardPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedSort = parseSortMode(searchParams.get("sort"));

  const [rawSearch, setRawSearch] = useState("");
  const searchTerm = useDebouncedValue(rawSearch, 150);
  const [openTeamIds, setOpenTeamIds] = useState<ReadonlySet<number>>(() => new Set());
  const [isRealtimeConnected, setIsRealtimeConnected] = useState(false);

  const board = useBoardData({
    pollingMs: isRealtimeConnected ? false : REALTIME_POLL_MS,
  });

  const realtime = useLeagueBoardRealtime({
    seasonId: board.seasonId,
    season: board.season,
    week: board.week,
    onConnectionChange: setIsRealtimeConnected,
  });

  const filtered = useMemo(
    () => filterTeams(board.teams, searchTerm),
    [board.teams, searchTerm],
  );

  const effective = useMemo(
    () => selectEffectiveSortMode(filtered.teams, requestedSort),
    [filtered.teams, requestedSort],
  );

  const sorted = useMemo(
    () => sortBoardTeams(filtered.teams, effective.mode),
    [filtered.teams, effective.mode],
  );

  const autoExpanded = useMemo(
    () => new Set(filtered.autoExpandTeamIds),
    [filtered.autoExpandTeamIds],
  );

  const handleToggle = useCallback((teamId: number) => {
    setOpenTeamIds((current) => {
      const next = new Set(current);
      if (next.has(teamId)) {
        next.delete(teamId);
      } else {
        next.add(teamId);
      }
      return next;
    });
  }, []);

  const handleSortModeChange = useCallback(
    (mode: SortMode) => {
      // Sort lives in the URL so a member can share the view they are looking at.
      const next = new URLSearchParams(searchParams);
      next.set("sort", mode);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const isOpen = (teamId: number) =>
    openTeamIds.has(teamId) || autoExpanded.has(teamId);

  return (
    <main className="px-4 pb-10 sm:px-0">
      <BoardHeader
        week={board.week}
        sortMode={requestedSort}
        onSortModeChange={handleSortModeChange}
        sortFellBack={effective.fellBack}
        searchTerm={rawSearch}
        onSearchTermChange={setRawSearch}
        projectionsUpdatedAt={board.projectionsUpdatedAt}
        isRealtimeConnected={realtime.isConnected}
      />

      <div className="space-y-3">
        {realtime.isConnected ? null : (
          <RealtimeBanner onRefresh={board.refetchAll} />
        )}

        <BoardErrors errors={board.errors} onRetry={board.refetchAll} />

        {board.isPending ? <BoardSkeleton /> : null}
        {!board.isPending && board.isEmpty ? <BoardEmpty /> : null}

        {!board.isPending && !board.isEmpty ? (
          <>
            <ul className={GRID}>
              {sorted.active.map((team, index) => (
                <TeamCard
                  key={team.teamId}
                  team={team}
                  rank={index + 1}
                  isOpen={isOpen(team.teamId)}
                  onToggle={handleToggle}
                  highlightedPlayerIds={filtered.matchedPlayerIds}
                />
              ))}
            </ul>

            {sorted.eliminated.length > 0 ? (
              <>
                <EliminatedDivider count={sorted.eliminated.length} />
                <ul className={GRID}>
                  {sorted.eliminated.map((team, index) => (
                    <TeamCard
                      key={team.teamId}
                      team={team}
                      rank={sorted.active.length + index + 1}
                      isOpen={isOpen(team.teamId)}
                      onToggle={handleToggle}
                      highlightedPlayerIds={filtered.matchedPlayerIds}
                    />
                  ))}
                </ul>
              </>
            ) : null}
          </>
        ) : null}
      </div>

      {/*
        The only place the projection provider is named. Ben's decision 2 replaced the
        per-card and per-header disclaimers with this one line.
      */}
      <footer className="mt-6 text-xs text-muted-foreground">
        Projections: Sleeper
      </footer>
    </main>
  );
}
```

- [ ] **Step 6: Serve the board at `/` and keep `board` as a redirect**

Ben's decision 1: the board is the home page. This step repoints the router; Task 11 deletes
the files it stops referencing. Replace `apps/web/src/router.tsx` with:

```tsx
import {
  createBrowserRouter,
  Navigate,
  RouteObject,
  useLocation,
} from "react-router-dom";

import { BoardPage } from "@/app/board/BoardPage";
import ErrorPage from "@/app/error-page";
import App from "@/app/layout";

/**
 * The board was reviewed at `/board` and members have shared `/board?sort=faab` links, so the
 * path stays as a redirect that keeps the query string. Not exported, so the
 * `react-refresh/only-export-components` rule stays quiet about this file.
 */
function BoardRedirect() {
  const { search } = useLocation();
  return <Navigate to={{ pathname: "/", search }} replace />;
}

export const router = createBrowserRouter([
  {
    path: "/",
    Component: App,
    ErrorBoundary: ErrorPage,
    children: [
      {
        path: "",
        element: <BoardPage />,
      },
      {
        path: "board",
        element: <BoardRedirect />,
      },
      {
        path: "*",
        element: <Navigate to="/" replace />,
      },
    ],
  },
] satisfies RouteObject[]);
```

- [ ] **Step 7: Strip the layout down to the title and the theme toggle**

The nav pointed at pages that are about to be deleted, and the board carries its own header.
Replace `apps/web/src/app/layout.tsx` with:

```tsx
import { Outlet } from "react-router-dom";

import { ModeToggle } from "@/components/mode-toggle";

function App() {
  return (
    <div className="min-h-screen w-full bg-muted/40">
      <div className="mx-auto w-full max-w-6xl px-4 py-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h1 className="text-lg font-semibold">Ultimate Guillotine</h1>
          <ModeToggle />
        </div>
        <Outlet />
      </div>
    </div>
  );
}

export default App;
```

`ModeToggle` is `apps/web/src/components/mode-toggle.tsx`. It already exists, already renders
against the existing `ThemeProvider`, and is currently imported by nothing — this is its
first real use, so it stays while `Nav` goes.

- [ ] **Step 8: Run the test to verify it passes**

Run: `pnpm --filter @ultimate-guillotine/web test src/app/board/BoardPage.test.tsx`
Expected: PASS — 11 tests.

- [ ] **Step 9: Build, lint and commit**

The old pages are unreferenced now but still on disk, and `tsc` still typechecks them. Prove
the build is green *before* Task 11 deletes them, so a Task 11 failure can only mean the
deletion went too far.

```bash
pnpm --filter @ultimate-guillotine/web build
pnpm lint
git add apps/web/src/board/components/BoardStates.tsx \
  apps/web/src/board/components/BoardHeader.tsx \
  apps/web/src/app/board/BoardPage.tsx apps/web/src/app/board/BoardPage.test.tsx \
  apps/web/src/router.tsx apps/web/src/app/layout.tsx
git commit -m "feat: serve the league board at / with a /board redirect"
```

---

### Task 11: Delete the legacy site

Ben's decision 1 scraps the rest of the old site. Task 10 already stopped referencing it, so
this task is a pure deletion plus one import removal in `main.tsx`. Nothing here is a
judgement call: every file below was traced to exactly one consumer chain, and every consumer
in that chain is also in the list.

**Files:**
- Delete: 30 files (listed in Step 1)
- Modify: `apps/web/src/main.tsx` (drop `PlayerDataProvider`)

**Interfaces:**
- Consumes: nothing. Task 10's router and layout already point away from all of it.
- Produces: an `apps/web/src` whose only data code is `src/board/`.

- [ ] **Step 1: Confirm nothing outside the deletion set still imports it**

Run this before deleting anything. It lists every import of the doomed modules; every hit
must itself be a file in the deletion set.

```bash
cd apps/web
grep -rn -E "app/(constants|PlayerDataContext)|app/home/|app/status/|app/rosters/|app/rules/|app/history/|queries/|components/roster-table/|PlayerDataManager" src/ \
  | grep -v -E "^src/(app/(home|status|rosters|rules|history)/|app/constants|app/PlayerDataContext|queries/|components/roster-table/|components/PlayerDataManager)"
```

Expected: exactly one line, `src/main.tsx` importing `PlayerDataProvider` — which Step 3
removes. Any other line is a file that still needs the legacy code; stop and resolve it
before deleting.

- [ ] **Step 2: Delete the files**

```bash
cd apps/web
git rm -r \
  src/app/home \
  src/app/rosters \
  src/app/rules \
  src/app/history \
  src/app/status \
  src/queries \
  src/components/roster-table \
  src/app/constants.ts \
  src/app/PlayerDataContext.tsx \
  src/components/PlayerDataManager.tsx \
  fetchPlayerData.js
```

That is thirty tracked files:

| Directory or file | Files removed |
| --- | --- |
| `src/app/home/` | `HomePage.tsx`, `HeaderAnalytics.tsx`, `RosterCard.tsx`, `getCurrentGulag.ts`, `Nav.tsx`, `MobileNav.tsx`, `nav-items.ts` (7) |
| `src/app/rosters/` | `RostersPage.tsx` (1) |
| `src/app/rules/` | `RulesPage.tsx`, `LeagueScheduleTable.tsx`, `guillotine-league-rules.md` (3) |
| `src/app/history/` | `HistoryPage.tsx` (1) |
| `src/app/status/` | `LeagueStatus.tsx`, `MobileLeagueStatus.tsx`, `generateLeagueStatusData.tsx` (3) |
| `src/queries/` | `useLeagueRosters.tsx`, `useLeagueUsers.tsx`, `useLeagueGulagData.tsx`, `usePlayerProjections.tsx`, `usePlayerProjections_SleeperDeprecated.tsx` (5) |
| `src/components/roster-table/` | `RosterGrid.tsx`, `RosterTable.tsx`, `TeamRosterCard.tsx`, `getOwnerByRosterId.ts`, `getRosterData.ts`, `useGetPlayersFromRoster.ts` (6) |
| `src/app/constants.ts` | the hard-coded league id, `CURRENT_WEEK` and `owners` list (1) |
| `src/app/PlayerDataContext.tsx` | the `/nfl_players.json` context provider (1) |
| `src/components/PlayerDataManager.tsx` | the unused `/nfl_players.json` debug panel (1) |
| `fetchPlayerData.js` | the Node script that downloaded `public/nfl_players.json` (1) |

`apps/web/public/nfl_players.json` is a 12 MB local artifact that is **already gitignored and
untracked**, so `git rm` neither can nor needs to touch it. Delete it from the working copy by
hand if you want the disk space back (`rm apps/web/public/nfl_players.json`); nothing reads it
once `PlayerDataContext` is gone.

Everything else stays, and none of it imported the deleted code:
`src/components/ui/`, `src/components/mode-toggle.tsx` (now used by the layout),
`src/components/icons.tsx` (used by `mode-toggle`), `src/components/theme-provider.tsx`,
`src/components/theme-context.ts`, `src/components/tailwind-indicator.tsx`,
`src/app/error-page.tsx`, `src/app/index.tsx`, `src/QueryProvider.tsx`, `src/queryClient.ts`,
`src/supabaseClient.ts`, `src/lib/`, and all of `src/board/`.

- [ ] **Step 3: Drop `PlayerDataProvider` from `main.tsx`**

Replace `apps/web/src/main.tsx` with:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";

import "./globals.css";

import { RouterProvider } from "react-router-dom";

import { ThemeProvider } from "@/components/theme-provider";

import { TailwindIndicator } from "./components/tailwind-indicator.tsx";
import { TooltipProvider } from "./components/ui/tooltip.tsx";
import { QueryProvider } from "./QueryProvider.tsx";
import { router } from "./router.tsx";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider defaultTheme="dark" storageKey="vite-ui-theme">
      <QueryProvider>
        <TailwindIndicator />
        <TooltipProvider delayDuration={200}>
          <RouterProvider router={router} />
        </TooltipProvider>
      </QueryProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
```

`TooltipProvider` stays: `TeamCard`'s caveat badges use plain `title` attributes, but the
shadcn `Tooltip` primitives remain vendored and the provider is cheap insurance for the next
component that reaches for one.

- [ ] **Step 4: Prove nothing references a deleted module**

```bash
cd apps/web
grep -rn -E "roster-table|useLeagueRosters|useLeagueUsers|useLeagueGulagData|usePlayerProjections|PlayerDataContext|PlayerDataManager|nav-items|app/constants|nfl_players" src/ ; echo "exit: $?"
```

Expected: no output and `exit: 1` — grep's "no matches" code. Any hit is a dangling import
that `tsc` is about to fail on anyway.

- [ ] **Step 5: Prove the build still passes**

This is the step that actually certifies the deletion. Run all four:

```bash
pnpm --filter @ultimate-guillotine/web test
pnpm lint
pnpm --filter @ultimate-guillotine/web build
```

Expected:
- `test`: PASS, the same suite as Task 10 — no board test imported any deleted file, so the
  count does not move.
- `lint`: exit 0. ESLint is configured over `apps/web` as a whole; with `src/queries/` and
  `src/components/roster-table/` gone it has strictly less to check.
- `build`: `tsc` reports no errors and Vite writes `apps/web/dist`. `tsc` type-checked those
  files until a moment ago, so a green build here is direct proof that nothing survived that
  needed them. Watch the Vite output shrink as well — the `axios`, `graphql-request` and
  `match-sorter` chunks the legacy hooks pulled in should no longer appear.

If `tsc` fails, the error names the file and the missing import: either that file also belongs
in the deletion set (add it and re-run) or it is a genuine consumer and the deletion was too
broad (restore just that module with `git checkout -- <path>`).

- [ ] **Step 6: Smoke-test the routes**

```bash
pnpm dev
```

Check three URLs, then stop the server:
1. `http://localhost:5173/` renders the board.
2. `http://localhost:5173/board?sort=faab` lands on `/?sort=faab` with the FAAB sort applied.
3. `http://localhost:5173/rosters` — a now-deleted path — redirects to `/` rather than
   showing the error page.

- [ ] **Step 7: Commit**

```bash
git add -A apps/web
git commit -m "refactor: delete the legacy web pages, hooks and player-JSON pipeline

The board is the whole site now. Removes the rosters, rules and history pages, the old
home page and its status tables, the direct-Sleeper query hooks, the roster-table
components, the local nfl_players.json pipeline and the nav.

- 30 files deleted
- pnpm --filter @ultimate-guillotine/web test: pass
- pnpm lint: clean
- pnpm --filter @ultimate-guillotine/web build: pass"
```

---

### Task 12: Full verification and the manual mobile check

Everything green together, plus the 375 px check the board spec requires before merge.

**Files:**
- No source changes expected. If a check fails, fix it in the file it points at and re-run.

**Interfaces:**
- Consumes: everything from Tasks 1–11.
- Produces: a verified build and a recorded manual check.

- [ ] **Step 1: Run the full unit suite**

Run: `pnpm test:web`
Expected: PASS — every test from Tasks 1–10 (roughly 90 tests across 11 files), zero skipped. Task 11 deleted no tests, because none of the legacy files had any.

- [ ] **Step 2: Run lint across the workspace**

Run: `pnpm lint`
Expected: exit 0 with no output. `--max-warnings 0` means a single `react-refresh/only-export-components` warning fails here; if one appears, move the non-component export out of the `.tsx` file into a `.ts` file rather than disabling the rule.

- [ ] **Step 3: Run the production build**

Run: `pnpm --filter @ultimate-guillotine/web build`
Expected: `tsc` reports no errors, then Vite writes `apps/web/dist`. This is the same command Vercel runs (`vercel.json` sets `buildCommand: "pnpm build"`, `outputDirectory: "apps/web/dist"`). `tsc` typechecks the test files too, so a type drift between the `Database` type and a fixture fails here.

- [ ] **Step 4: Confirm the agents suite still passes**

Run: `pnpm test:agents`
Expected: PASS — this plan touches no Python, so this is a guard that the root `package.json` edit in Task 1 did not disturb the existing scripts.

- [ ] **Step 4b: Confirm the deletion actually landed**

```bash
test ! -e apps/web/src/queries && test ! -e apps/web/src/components/roster-table \
  && test ! -e apps/web/fetchPlayerData.js && echo "legacy site gone"
```

Expected: `legacy site gone`.

- [ ] **Step 5: Manual mobile check at 375 px**

```bash
pnpm dev
```

Open `http://localhost:5173/board` and, in the browser's device toolbar, set the viewport to **375 × 812**. Work through this list and note the result of each in the commit message:

1. **Single column.** Every card is full width; the page does not scroll horizontally at any scroll position.
2. **Sticky header.** Scroll down — the header stays pinned, and the sort toggles and search field remain tappable.
3. **Expansion.** Tap one card. The roster opens in place with a "Starters" heading, then "Bench"; the chevron rotates; tapping again collapses it and focus returns to the toggle button.
4. **Both themes.** Toggle dark and light with the existing mode toggle. No hard-coded colour shows through — text stays readable on `bg-card` in both.
5. **Sort in the URL.** Tap "FAAB". The order changes and the address bar reads `/board?sort=faab`. Reload the page: the FAAB sort survives.
6. **Search.** Type a player surname. Only the holding team stays, its card auto-expands, and the matched player row is highlighted.
7. **Eliminated group.** If any team is eliminated, it renders dimmed under the "Eliminated (N)" divider, below every active team, and stays there when the sort changes.
8. **Live update.** Trigger a sync on the Mac mini (`ug sleeper sync`). Within a few seconds the "updated N seconds ago" line resets without the page reloading and without the card layout shifting.
9. **Reconnect indicator.** In devtools, set the network to Offline. Within a few seconds the header gains the muted "reconnecting" label and the "Live updates are paused" banner appears under it, with the already-loaded data still on screen. Go back online: the banner clears and the board refetches.
10. **Reduced motion.** Enable "Emulate CSS prefers-reduced-motion: reduce" in devtools' Rendering panel. Expanding a card becomes an instant state change with no slide animation.

Stop the dev server when finished.

- [ ] **Step 6: Record the verification**

```bash
git commit --allow-empty -m "chore: verify league board build, lint, tests and 375px manual check

- pnpm test:web: pass
- pnpm lint: clean
- pnpm --filter @ultimate-guillotine/web build: pass
- pnpm test:agents: pass
- manual 375px check: single column, sticky header, expansion, light and dark,
  sort in URL, search auto-expand, eliminated group, live sync, reconnect banner,
  reduced motion"
```

- [ ] **Step 7: Open the pull request and confirm on the Vercel preview**

Push the branch and open a PR. On the Vercel preview URL, repeat steps 5.1, 5.3, 5.4 and 5.8 at 375 px so Ben reviews the deployed board rather than a local dev server, as the board spec's Done criteria require.

---

## Remaining open questions for Ben

These stay open — none of them block this plan, and each is implemented in a way that a one-line change flips:

1. **Promote to `/`?** The board ships at `/board` with a nav link. The board spec recommends promoting it to the home page after a week of live use; that is a follow-up.
2. **Provider naming.** The header says "Projections from Sleeper" once rather than naming the provider on every card (Spec issue 8).
3. **Eliminated rosters.** They stay expandable, frozen at whatever `roster_holdings` currently holds. Freezing or permanently collapsing them is a change inside `TeamCard`.
4. **Display names.** `public.members.display_name` is used as-is. `private.member_aliases` is never read, per the board's privacy rule.
5. **Below-gate projections.** Implemented as number-plus-caveat (Spec issue 4). Reverting to hiding the number entirely is a single branch in `resolveProjectionDisplay`.
