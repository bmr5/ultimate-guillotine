# League History Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship two public read-only pages in `apps/web` — a filterable trade catalog at `/trades` and a season-by-season league history at `/history` — fed by two new anon-readable Supabase tables that Ben loads from the Mac mini with `ug history load-catalog` and `ug history load-results`.

**Architecture:** Two operator-run Python loaders write `public.trade_catalog` and `public.season_results` through one `HistoryRepository`, upserting on the natural keys `catalog_id` and `season`; both copy fields through explicit allowlists so private analyst notes and the workbook's dues column can never reach a public table. The web side adds `src/history/` beside the existing `src/board/`: one TanStack Query hook per table, four single-table reads, and pure functions under `src/history/derive/` that union catalog rows with registered `public.trades` rows, filter them, and compute the stats strip. There is no Realtime channel — both tables change by hand a few times a year, so the pages use a five-minute `staleTime` and `refetchOnWindowFocus`.

**Tech Stack:** Python 3.12 + psycopg 3 + openpyxl + pytest (the `packages/league-automation` package, run with `uv`); Postgres 15 + pgTAP via the local Supabase stack; React 18, TypeScript 5, Vite 4, react-router-dom 6, TanStack Query 5, `@supabase/supabase-js` 2, Tailwind 3 with the shadcn/Radix primitives already vendored under `apps/web/src/components/ui/`, Vitest 3.2.7 + `@testing-library/react` 16 (already installed by the board plan).

**Spec:** `docs/superpowers/specs/2026-09-09-league-history-pages-design.md`. It reads owner labels from the columns defined in `docs/superpowers/specs/2026-09-09-league-data-layer-design.md` and merges with the trades described in `docs/superpowers/specs/2026-09-09-league-history-backfill-design.md`. Read all three before starting.

## Global Constraints

- **Dues are private.** Nothing in this plan may read, store, print, or render the workbook's `paid` column, the 2025 roster block (seat number, first name, last name, `paid`, replacement / `removed` columns), or the 2023 signup block at rows 28–48. The loader reads a fixed sheet allowlist: `("Winners", "2023", "2024")`.
- **Chat text is private.** `notes` and `source_texts` from `data/private/analysis/trade-classification.json` are never loaded. `load-catalog` copies through the allowlist `("id", "season", "week_or_date", "type", "structure", "parties", "assets", "faab_total", "confidence")` — never by deleting keys from a copied dict.
- **No names in the public tables.** Parties and champions are stored as `public.members` ids. An unresolved person increments a count column (`unresolved_parties`, `unresolved_names`); the raw workbook or JSON name is discarded.
- **Owner labels** are `public.members.nickname` when set, otherwise `public.members.sleeper_display_name`. Never `members.display_name` (the bare Sleeper username), never `private.member_aliases`. Reuse `resolveOwnerLabel` from `apps/web/src/board/derive/join.ts`.
- **Loader output is counts only.** Exact formats: `catalog: <n> rows, <n> updated, <n> unresolved parties` and `results: <n> seasons, <n> unresolved names`, plus `skipped: <n>` on stderr-free skips. No member name, player name, nickname, or source text is ever printed.
- Both loaders are idempotent: rerunning produces byte-identical rows. `load-catalog` upserts on `catalog_id`, `load-results` on `season`.
- Every new public table follows the existing shape in `supabase/migrations/20260908204333_public_league_schema.sql`: identity primary key, `created_at timestamptz not null default now()`, `enable row level security`, `revoke all ... from anon, authenticated`, `grant select ... to anon, authenticated`, a `"Public <table> are readable" ... for select using (true)` policy, an `"Automation writes <table>" ... for all to automation_worker using (true) with check (true)` policy, and `grant select, insert, update ... to automation_worker`. **No `delete` grant on either new table** — `roster_holdings` stays the only public table `automation_worker` may delete from.
- The pages are read-only and unauthenticated: no write path, no auth, no per-member view.
- **No Realtime.** Neither page opens a Supabase channel and neither sets a `refetchInterval`. `staleTime` is `5 * 60 * 1000`; `refetchOnWindowFocus` stays at its default `true`.
- Designed at 375 px first, single column; two-up at `sm`. Semantic Tailwind tokens only (`bg-card`, `text-muted-foreground`, `border`, `bg-accent`) — **no hard-coded hex values**. Dark mode is the existing class-strategy `ThemeProvider` in `apps/web/src/main.tsx`.
- Each page is a `<ul>` of `<li>` cards; every expand control is a real `<button>` with `aria-expanded` and `aria-controls`; filter state lives in the URL query string.
- Lint must stay clean: `pnpm lint` runs `eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0`. `react-refresh/only-export-components` is a warning and warnings fail, so a `.tsx` file may export components only — constants and types go in `.ts` files.
- `apps/web/tsconfig.json` has `strict`, `noUnusedLocals` and `noUnusedParameters` on, and `pnpm --filter @ultimate-guillotine/web build` runs `tsc` over everything in `src`, test files included.
- Python style follows the package: `ruff` clean (`pnpm lint:agents`), docstrings that say *why*, repositories that take a `psycopg.Connection` and never open their own.
- Commit after every task.

---

## Spec issues

Five gaps found checking the spec against the repository. Each is resolved here and the resolution is implemented below.

1. **`public.trade_revisions.terms` carries chat text and Sleeper usernames, and anon can already read it.** `TradeRepository._accept` stores `TradeProposal.model_dump(mode="json")`, which includes `evidence_excerpt` (a verbatim excerpt of the league's message) and `parties[].display_name` (the bare Sleeper username), and `supabase/migrations/20260908204333_public_league_schema.sql:152` grants `select` on that table to `anon`. The spec's "no chat text, no usernames" rule cannot be met by a page that selects `terms` wholesale. **Resolution:** the registered-trade fetcher selects only safe JSON paths — `kind:terms->>kind`, `assets:terms->assets`, `parties:terms->parties` — and `normalizeRegisteredTrade` reads only `member_id` out of each party and drops every asset field except `kind`, `player_id`, `player_name`, `amount`, `from_member_id`, `to_member_id` (Task 5, Task 6). The underlying exposure is **not** fixed here — it predates this feature and belongs to the Registrar — and is raised in "Still open" for Ben.
2. **Party nicknames have three possible sources and the spec names none.** `MemberAliasRepository.all_members()` returns `MemberRef(member_id, display_name, aliases, nickname)`. **Resolution:** `build_label_index` maps `normalize_name` of every alias, of `nickname`, and of `display_name` to a member id; a token matching two different member ids is ambiguous and counts as unresolved rather than picking one (Task 3).
3. **`trade_catalog.season_id` cannot be filled for pre-2023 seasons.** No `public.seasons` row exists for them, and the backfill may add one later. **Resolution:** the loader resolves `season_id` by year on **every** run and writes null when there is no row, so a rerun after the backfill fills it in; the page never depends on it and joins by the plain `season` year.
4. **`public.trades` has no year column.** It carries `season_id`, so `/trades` cannot group registered trades by year without a join. **Resolution:** the trades fetcher uses PostgREST embedding, `select("id, trade_code, status, season_id, seasons ( year )")`, and `fetchSeasons` supplies the same mapping for the season filter chips.
5. **The typed Supabase client is board-scoped.** `apps/web/src/board/boardClient.ts` says "nothing outside `src/board` should import it", but the history pages need the same typed client. **Resolution:** the `Database` type in `apps/web/src/board/types.ts` gains the four tables these pages read, and `boardClient.ts`'s comment is updated to name it the app's shared typed client. No second `Database` type is introduced — two of them over one connection would drift.

---

## File Structure

**New, Python (`packages/league-automation/`):**

| File | Responsibility |
| --- | --- |
| `src/ultimate_guillotine/history/__init__.py` | Empty package marker. |
| `src/ultimate_guillotine/history/models.py` | `CatalogRow` and `SeasonResultRow` dataclasses — the only shapes that reach Postgres. |
| `src/ultimate_guillotine/history/repository.py` | `HistoryRepository`: two upserts, each returning `"inserted"` or `"updated"`. |
| `src/ultimate_guillotine/history/catalog.py` | The classification-JSON reader: field allowlist, label index, party resolution, `CatalogRow` construction. |
| `src/ultimate_guillotine/history/records.py` | The workbook reader: sheet allowlist, `Winners` rows, the 2023 and 2024 elimination grids. |
| `src/ultimate_guillotine/cli/history.py` | `ug history load-catalog` and `ug history load-results`. |
| `tests/history/__init__.py`, `tests/history/test_repository.py`, `tests/history/test_catalog.py`, `tests/history/test_records.py` | Unit and local-stack tests. |
| `tests/cli/test_history.py` | Command wiring, counts-only output, exit codes. |

**New, SQL:**

| File | Responsibility |
| --- | --- |
| `supabase/migrations/20260909210000_league_history_pages.sql` | Both tables, RLS, policies, grants, indexes. |
| `supabase/tests/league_history_pages.sql` | pgTAP: existence, RLS, policies, no `delete` grant, checks, uniques. |

**New, web (`apps/web/src/`):**

| File | Responsibility |
| --- | --- |
| `history/queryKeys.ts` | Every TanStack Query key the two pages use. |
| `history/fetchers.ts` | One async fetcher per table; throws a labelled `Error`. |
| `history/types.ts` | Domain types: `CatalogTrade`, `TradeAsset`, `SeasonResult`, `TradeFilters`, filter parsing. |
| `history/derive/merge.ts` | `normalizeRegisteredTrade`, `mergeTradeSources`. |
| `history/derive/filter.ts` | `filterTrades` and the filter-option builders. |
| `history/derive/stats.ts` | `tradeStats` for the stats strip. |
| `history/useTradeCatalog.ts` | The `/trades` queries plus the memoised merge. |
| `history/useSeasonResults.ts` | The `/history` queries plus owner labelling. |
| `history/components/TradeCard.tsx`, `TradeFilterBar.tsx`, `StatsStrip.tsx` | `/trades` UI. |
| `history/components/SeasonCard.tsx`, `WinnersStrip.tsx` | `/history` UI. |
| `app/trades/TradesPage.tsx`, `app/history/HistoryPage.tsx` | Page assembly and URL state. |

**Modified:** `apps/web/src/board/types.ts` (four tables added to `Database`), `apps/web/src/board/boardClient.ts` (comment), `apps/web/src/router.tsx` (two routes), `apps/web/src/app/layout.tsx` (nav), `packages/league-automation/src/ultimate_guillotine/cli/main.py` (register `history`).

---

### Task 1: Migration and pgTAP

**Files:**
- Create: `supabase/migrations/20260909210000_league_history_pages.sql`
- Create: `supabase/tests/league_history_pages.sql`

**Interfaces:**
- Produces: `public.trade_catalog` and `public.season_results` with the exact column names every later task types and selects.

- [ ] **Step 1: Write the failing pgTAP test**

```sql
-- supabase/tests/league_history_pages.sql
begin;
select plan(14);

select has_table('public', 'trade_catalog', 'trade_catalog table exists');
select has_table('public', 'season_results', 'season_results table exists');

select is(
  (select relrowsecurity from pg_class where oid = 'public.trade_catalog'::regclass),
  true, 'trade_catalog has row level security enabled'
);
select is(
  (select relrowsecurity from pg_class where oid = 'public.season_results'::regclass),
  true, 'season_results has row level security enabled'
);

select policies_are(
  'public', 'trade_catalog',
  array['Public trade_catalog are readable', 'Automation writes trade_catalog']
);
select policies_are(
  'public', 'season_results',
  array['Public season_results are readable', 'Automation writes season_results']
);

-- History is not retracted from a laptop: roster_holdings stays the only deletable table.
select is_empty(
  $$select table_name from information_schema.role_table_grants
     where grantee = 'automation_worker' and table_schema = 'public'
       and privilege_type = 'DELETE' and table_name <> 'roster_holdings'$$,
  'automation_worker holds DELETE on no history table'
);
select table_privs_are(
  'public', 'trade_catalog', 'anon', array['SELECT'],
  'anon may only read trade_catalog'
);
select table_privs_are(
  'public', 'season_results', 'anon', array['SELECT'],
  'anon may only read season_results'
);

-- A bad confidence or source must be refused by the database, not only by the loader.
select throws_ok(
  $$insert into public.trade_catalog
      (catalog_id, season, trade_type, structure, party_count, confidence, loaded_at)
    values ('bad-conf', 2025, 'trade', '1-for-1', 2, 'certain', now())$$,
  '23514', null, 'confidence is constrained to high/medium/low'
);
select throws_ok(
  $$insert into public.trade_catalog
      (catalog_id, season, trade_type, structure, party_count, confidence, source, loaded_at)
    values ('bad-src', 2025, 'trade', '1-for-1', 2, 'high', 'guessed', now())$$,
  '23514', null, 'source is constrained to catalog/registered'
);

-- The natural keys the loaders upsert on.
insert into public.trade_catalog
  (catalog_id, season, trade_type, structure, party_count, confidence, loaded_at)
values ('dup-1', 2025, 'trade', '1-for-1', 2, 'high', now());
select throws_ok(
  $$insert into public.trade_catalog
      (catalog_id, season, trade_type, structure, party_count, confidence, loaded_at)
    values ('dup-1', 2025, 'trade', '1-for-1', 2, 'high', now())$$,
  '23505', null, 'catalog_id is unique'
);
insert into public.season_results (season, loaded_at) values (1999, now());
select throws_ok(
  $$insert into public.season_results (season, loaded_at) values (1999, now())$$,
  '23505', null, 'season is unique'
);

select has_column('public', 'trade_catalog', 'party_member_ids', 'parties are stored as ids');

select * from finish();
rollback;
```

- [ ] **Step 2: Run it to verify it fails**

Run: `supabase db reset && supabase test db`
Expected: FAIL — `relation "public.trade_catalog" does not exist`.

- [ ] **Step 3: Write the migration**

```sql
-- supabase/migrations/20260909210000_league_history_pages.sql
-- Public history: the analyst's trade catalog and one row of results per season. Same shape
-- as the nine existing public tables, minus any DELETE grant: history is not retracted.

-- Neither table stores a person's name. Parties and champions are public.members ids; a name
-- the loader could not resolve becomes a count, so nothing here can leak a nickname or a
-- workbook cell. `season` is the plain year, not season_id: the catalog reaches back past the
-- seasons the league has rows for. season_id is filled in when a row exists, and a rerun after
-- the backfill fills it in for seasons that gained one.
create table public.trade_catalog (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  catalog_id text not null unique,
  season int not null,
  season_id bigint references public.seasons (id),
  week int,
  occurred_on date,
  trade_type text not null,
  structure text not null,
  party_member_ids bigint[] not null default '{}',
  party_count int not null,
  assets jsonb not null default '[]',
  faab_total int,
  confidence text not null check (confidence in ('high', 'medium', 'low')),
  source text not null default 'catalog' check (source in ('catalog', 'registered')),
  unresolved_parties int not null default 0,
  loaded_at timestamptz not null
);

create index trade_catalog_season_idx on public.trade_catalog (season);
create index trade_catalog_trade_type_idx on public.trade_catalog (trade_type);
create index trade_catalog_parties_idx on public.trade_catalog using gin (party_member_ids);

create table public.season_results (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season int not null unique,
  season_id bigint references public.seasons (id),
  champion_member_id bigint references public.members (id),
  co_champion_member_id bigint references public.members (id),
  runner_up_member_id bigint references public.members (id),
  third_member_id bigint references public.members (id),
  team_count int,
  -- Ordered, one entry per week. Named entries come from the Adjudicator's league_events for
  -- 2026 on; 2023 and 2024 carry the records workbook's counts with member_id null.
  eliminations jsonb not null default '[]',
  notes text,
  unresolved_names int not null default 0,
  source text not null default 'records-xlsx',
  loaded_at timestamptz not null
);

alter table public.trade_catalog enable row level security;
alter table public.season_results enable row level security;

revoke all on public.trade_catalog from anon, authenticated;
revoke all on public.season_results from anon, authenticated;
grant select on public.trade_catalog to anon, authenticated;
grant select on public.season_results to anon, authenticated;

create policy "Public trade_catalog are readable" on public.trade_catalog for select using (true);
create policy "Public season_results are readable" on public.season_results for select using (true);

create policy "Automation writes trade_catalog" on public.trade_catalog
  for all to automation_worker using (true) with check (true);
create policy "Automation writes season_results" on public.season_results
  for all to automation_worker using (true) with check (true);

grant select, insert, update on public.trade_catalog to automation_worker;
grant select, insert, update on public.season_results to automation_worker;
grant usage, select on all sequences in schema public to automation_worker;
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `supabase db reset && supabase test db`
Expected: PASS — `league_history_pages.sql .. ok`, and the existing `league_data_layer.sql`, `public_league_schema.sql` and `trades.sql` files still pass.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/20260909210000_league_history_pages.sql supabase/tests/league_history_pages.sql
git commit -m "feat: add trade_catalog and season_results public tables"
```

---

### Task 2: History repository

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/history/__init__.py` (empty)
- Create: `packages/league-automation/src/ultimate_guillotine/history/models.py`
- Create: `packages/league-automation/src/ultimate_guillotine/history/repository.py`
- Test: `packages/league-automation/tests/history/__init__.py` (empty), `packages/league-automation/tests/history/test_repository.py`

**Interfaces:**
- Consumes: the tables from Task 1.
- Produces: `CatalogRow`, `SeasonResultRow`, and `HistoryRepository(conn)` with `upsert_catalog(row: CatalogRow) -> str` and `upsert_season_result(row: SeasonResultRow) -> str`, each returning `"inserted"` or `"updated"`, plus `season_id_for(year: int) -> int | None`.

- [ ] **Step 1: Write the failing test**

```python
# packages/league-automation/tests/history/test_repository.py
"""The two upserts, against the local stack. `conn` rolls back, so these leave nothing."""

from datetime import UTC, datetime

from ultimate_guillotine.history.models import CatalogRow, SeasonResultRow
from ultimate_guillotine.history.repository import HistoryRepository

LOADED_AT = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def _row(**overrides) -> CatalogRow:
    base = dict(
        catalog_id="2025-014",
        season=2025,
        season_id=None,
        week=4,
        occurred_on=None,
        trade_type="rental",
        structure="player-for-faab",
        party_member_ids=[],
        party_count=2,
        assets=[{"kind": "faab", "amount": 12, "from_party": 0, "to_party": 1}],
        faab_total=12,
        confidence="high",
        unresolved_parties=2,
        loaded_at=LOADED_AT,
    )
    base.update(overrides)
    return CatalogRow(**base)


def test_catalog_upsert_inserts_then_updates(conn) -> None:
    repo = HistoryRepository(conn)

    assert repo.upsert_catalog(_row()) == "inserted"
    assert repo.upsert_catalog(_row(faab_total=15, confidence="medium")) == "updated"

    with conn.cursor() as cur:
        cur.execute(
            "select count(*), max(faab_total), max(confidence) from public.trade_catalog"
            " where catalog_id = %s",
            ("2025-014",),
        )
        assert cur.fetchone() == (1, 15, "medium")


def test_catalog_rerun_is_byte_identical(conn) -> None:
    """The idempotency claim, checked as a whole-row comparison rather than a count."""
    repo = HistoryRepository(conn)
    repo.upsert_catalog(_row())
    with conn.cursor() as cur:
        cur.execute("select to_jsonb(t) - 'id' - 'created_at' from public.trade_catalog t")
        first = cur.fetchone()[0]
    repo.upsert_catalog(_row())
    with conn.cursor() as cur:
        cur.execute("select to_jsonb(t) - 'id' - 'created_at' from public.trade_catalog t")
        assert cur.fetchone()[0] == first


def test_season_result_upsert_and_season_id_lookup(conn) -> None:
    repo = HistoryRepository(conn)
    season_id = repo.season_id_for(2026)
    assert season_id is not None, "supabase seed inserts the 2026 season row"
    assert repo.season_id_for(1999) is None

    row = SeasonResultRow(
        season=2024,
        season_id=None,
        champion_member_id=None,
        co_champion_member_id=None,
        runner_up_member_id=None,
        third_member_id=None,
        team_count=19,
        eliminations=[{"week": 2, "order": 1, "member_id": None, "gulag_out": 2,
                       "pool_out": 0, "remaining": None, "note": None}],
        notes=None,
        unresolved_names=1,
        loaded_at=LOADED_AT,
    )
    assert repo.upsert_season_result(row) == "inserted"
    assert repo.upsert_season_result(row) == "updated"

    with conn.cursor() as cur:
        cur.execute("select team_count, eliminations from public.season_results where season = 2024")
        team_count, eliminations = cur.fetchone()
    assert team_count == 19
    assert eliminations[0]["gulag_out"] == 2
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/history/test_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ultimate_guillotine.history'`.

- [ ] **Step 3: Write the models and the repository**

```python
# packages/league-automation/src/ultimate_guillotine/history/models.py
"""The only two shapes that reach the public history tables.

Deliberately id-only: no member name, nickname, or workbook cell has a field to
live in, so nothing private can be carried into Postgres by accident.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class CatalogRow:
    catalog_id: str
    season: int
    season_id: int | None
    week: int | None
    occurred_on: date | None
    trade_type: str
    structure: str
    party_member_ids: list[int]
    party_count: int
    assets: list[dict[str, Any]]
    faab_total: int | None
    confidence: str
    unresolved_parties: int
    loaded_at: datetime


@dataclass(frozen=True)
class SeasonResultRow:
    season: int
    season_id: int | None
    champion_member_id: int | None
    co_champion_member_id: int | None
    runner_up_member_id: int | None
    third_member_id: int | None
    team_count: int | None
    eliminations: list[dict[str, Any]] = field(default_factory=list)
    notes: str | None = None
    unresolved_names: int = 0
    loaded_at: datetime | None = None
```

```python
# packages/league-automation/src/ultimate_guillotine/history/repository.py
"""Writes for the two public history tables.

Both upsert on a natural key, so a rerun after Ben fixes an alias updates the row
in place rather than allocating a second one. `xmax = 0` is Postgres' own answer to
"did this INSERT ... ON CONFLICT insert or update", which beats a prior SELECT.
"""

import psycopg
from psycopg.types.json import Jsonb

from ultimate_guillotine.history.models import CatalogRow, SeasonResultRow


class HistoryRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def season_id_for(self, year: int) -> int | None:
        """The public.seasons id for a year, or None for a season the league has no row for."""
        with self._conn.cursor() as cur:
            cur.execute("select id from public.seasons where year = %s", (year,))
            row = cur.fetchone()
        return row[0] if row else None

    def upsert_catalog(self, row: CatalogRow) -> str:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into public.trade_catalog (
                    catalog_id, season, season_id, week, occurred_on, trade_type, structure,
                    party_member_ids, party_count, assets, faab_total, confidence,
                    unresolved_parties, loaded_at
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (catalog_id) do update set
                    season = excluded.season,
                    season_id = excluded.season_id,
                    week = excluded.week,
                    occurred_on = excluded.occurred_on,
                    trade_type = excluded.trade_type,
                    structure = excluded.structure,
                    party_member_ids = excluded.party_member_ids,
                    party_count = excluded.party_count,
                    assets = excluded.assets,
                    faab_total = excluded.faab_total,
                    confidence = excluded.confidence,
                    unresolved_parties = excluded.unresolved_parties,
                    loaded_at = excluded.loaded_at
                returning (xmax = 0)
                """,
                (
                    row.catalog_id, row.season, row.season_id, row.week, row.occurred_on,
                    row.trade_type, row.structure, row.party_member_ids, row.party_count,
                    Jsonb(row.assets), row.faab_total, row.confidence,
                    row.unresolved_parties, row.loaded_at,
                ),
            )
            inserted = cur.fetchone()[0]
        return "inserted" if inserted else "updated"

    def upsert_season_result(self, row: SeasonResultRow) -> str:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into public.season_results (
                    season, season_id, champion_member_id, co_champion_member_id,
                    runner_up_member_id, third_member_id, team_count, eliminations, notes,
                    unresolved_names, loaded_at
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (season) do update set
                    season_id = excluded.season_id,
                    champion_member_id = excluded.champion_member_id,
                    co_champion_member_id = excluded.co_champion_member_id,
                    runner_up_member_id = excluded.runner_up_member_id,
                    third_member_id = excluded.third_member_id,
                    team_count = excluded.team_count,
                    eliminations = excluded.eliminations,
                    -- A note Ben typed on an earlier run survives a run that passes none.
                    notes = coalesce(excluded.notes, public.season_results.notes),
                    unresolved_names = excluded.unresolved_names,
                    loaded_at = excluded.loaded_at
                returning (xmax = 0)
                """,
                (
                    row.season, row.season_id, row.champion_member_id,
                    row.co_champion_member_id, row.runner_up_member_id, row.third_member_id,
                    row.team_count, Jsonb(row.eliminations), row.notes,
                    row.unresolved_names, row.loaded_at,
                ),
            )
            inserted = cur.fetchone()[0]
        return "inserted" if inserted else "updated"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/history -v`
Expected: PASS, 3 tests. If they skip, `TEST_DATABASE_URL` is unset — export the local stack URL first (`supabase status` prints it).

- [ ] **Step 5: Commit**

```bash
git add packages/league-automation/src/ultimate_guillotine/history packages/league-automation/tests/history
git commit -m "feat: add history repository for trade catalog and season results"
```

---

### Task 3: The classification-JSON reader and `ug history load-catalog`

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/history/catalog.py`
- Create: `packages/league-automation/src/ultimate_guillotine/cli/history.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/main.py`
- Test: `packages/league-automation/tests/history/test_catalog.py`, `packages/league-automation/tests/cli/test_history.py`

**Interfaces:**
- Consumes: `HistoryRepository`, `CatalogRow`, `MemberAliasRepository.all_members()` returning `MemberRef(member_id, display_name, aliases, nickname)`, `normalize_name` from `ultimate_guillotine.trades.names`.
- Produces: `CATALOG_FIELDS`, `build_label_index(members) -> dict[str, int | None]`, `resolve_parties(names, index) -> tuple[list[int], int]`, `catalog_row(record, index, season_id, loaded_at) -> CatalogRow`, and `cmd_load_catalog(args) -> int`.

- [ ] **Step 1: Write the failing test**

```python
# packages/league-automation/tests/history/test_catalog.py
"""The reader's whole job is to drop things: private fields, unresolvable names, prose."""

from datetime import UTC, date, datetime

from ultimate_guillotine.history.catalog import (
    CATALOG_FIELDS,
    build_label_index,
    catalog_row,
    resolve_parties,
)
from ultimate_guillotine.trades.models import MemberRef

LOADED_AT = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
MEMBERS = [
    MemberRef(1, "owner-one", ("Alpha", "The Alpha"), "Alpha"),
    MemberRef(2, "owner-two", ("Bravo",), "Bravo"),
    MemberRef(3, "owner-three", ("Alpha",), "Alpha"),
]


def test_private_fields_are_not_in_the_allowlist() -> None:
    assert "notes" not in CATALOG_FIELDS
    assert "source_texts" not in CATALOG_FIELDS


def test_row_carries_no_private_field() -> None:
    record = {
        "id": "2025-014",
        "season": 2025,
        "week_or_date": 4,
        "type": "rental",
        "structure": "player-for-faab",
        "parties": ["Bravo", "Nobody"],
        "assets": [{"kind": "faab", "amount": 12, "from_party": 0, "to_party": 1}],
        "faab_total": 12,
        "confidence": "high",
        "notes": "SENTINEL-NOTE",
        "source_texts": ["SENTINEL-TEXT"],
    }
    index = build_label_index([MEMBERS[1]])
    row = catalog_row(record, index, season_id=None, loaded_at=LOADED_AT)

    assert "SENTINEL" not in repr(row)
    assert row.week == 4 and row.occurred_on is None
    assert row.party_member_ids == [2]
    assert row.party_count == 2
    assert row.unresolved_parties == 1


def test_week_or_date_accepts_an_iso_date() -> None:
    record = {
        "id": "2023-002", "season": 2023, "week_or_date": "2023-10-14", "type": "trade",
        "structure": "1-for-1", "parties": [], "assets": [], "confidence": "low",
    }
    row = catalog_row(record, {}, season_id=None, loaded_at=LOADED_AT)
    assert row.occurred_on == date(2023, 10, 14)
    assert row.week is None


def test_ambiguous_nickname_is_unresolved_rather_than_guessed() -> None:
    """Two members answer to "Alpha", so the catalog records a count, never a coin flip."""
    index = build_label_index(MEMBERS)
    ids, unresolved = resolve_parties(["Alpha", "Bravo"], index)
    assert ids == [2]
    assert unresolved == 1


def test_assets_drop_unknown_keys_and_free_text_conditions() -> None:
    record = {
        "id": "x", "season": 2025, "week_or_date": 1, "type": "trade", "structure": "1-for-1",
        "parties": [], "confidence": "high",
        "assets": [
            {"kind": "player", "sleeper_player_id": "4034", "name": "A Player",
             "position": "RB", "from_party": 0, "to_party": 1, "quote": "SENTINEL-QUOTE"},
            {"kind": "condition", "label": "rental", "text": "he said he'd give him back"},
            {"kind": "condition", "label": "handshake deal"},
        ],
    }
    row = catalog_row(record, {}, season_id=None, loaded_at=LOADED_AT)
    assert row.assets == [
        {"kind": "player", "sleeper_player_id": "4034", "name": "A Player",
         "position": "RB", "from_party": 0, "to_party": 1},
        {"kind": "condition", "label": "rental"},
    ]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/history/test_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ultimate_guillotine.history.catalog'`.

- [ ] **Step 3: Write the reader**

```python
# packages/league-automation/src/ultimate_guillotine/history/catalog.py
"""Read the analyst's trade classification into rows fit for a public table.

The file is private and stays private. Fields are copied through an allowlist
rather than by deleting `notes` and `source_texts` from a copy, so a field the
analyst adds next month is dropped by default instead of published by default --
which is the difference between a privacy rule and a privacy habit.
"""

from datetime import date, datetime
from typing import Any

from ultimate_guillotine.history.models import CatalogRow
from ultimate_guillotine.trades.models import MemberRef
from ultimate_guillotine.trades.names import normalize_name

#: The only keys read from a classification record. `notes` and `source_texts` are absent
#: on purpose and adding either is a privacy regression, not a feature.
CATALOG_FIELDS = (
    "id", "season", "week_or_date", "type", "structure", "parties", "assets",
    "faab_total", "confidence",
)

#: Asset fields that may be published, per kind. Everything else is dropped.
PLAYER_FIELDS = ("kind", "sleeper_player_id", "name", "position", "from_party", "to_party")
FAAB_FIELDS = ("kind", "amount", "from_party", "to_party")

#: A return condition is a label from this closed set, never prose: a free-text condition
#: is the one place a sentence out of the chat could reach a public page.
CONDITION_LABELS = frozenset({"rental", "return_after_week", "conditional", "keeper", "two_way"})

CONFIDENCE_VALUES = frozenset({"high", "medium", "low"})

#: Sentinel for a label two different members answer to. Kept in the index so an ambiguous
#: token is recognised as ambiguous rather than simply missing.
AMBIGUOUS = None


def build_label_index(members: list[MemberRef]) -> dict[str, int | None]:
    """Map every normalized label a member may be called by to their id.

    Aliases, the published nickname, and the Sleeper username all point at the same
    member. A label two members share maps to ``AMBIGUOUS``: the catalog would rather
    record an unresolved party than attribute a trade to the wrong person.
    """
    index: dict[str, int | None] = {}
    for member in members:
        labels = [*member.aliases, member.display_name]
        if member.nickname:
            labels.append(member.nickname)
        for label in labels:
            key = normalize_name(label)
            if not key:
                continue
            if key in index and index[key] != member.member_id:
                index[key] = AMBIGUOUS
            else:
                index.setdefault(key, member.member_id)
    return index


def resolve_parties(names: list[str], index: dict[str, int | None]) -> tuple[list[int], int]:
    """Resolve party nicknames to member ids, counting the ones that did not resolve.

    Order is the record's own, deduplicated, because a party list is a set of people
    and `assets` refers to them by position in the original list, not by id.
    """
    resolved: list[int] = []
    unresolved = 0
    for name in names:
        member_id = index.get(normalize_name(name or ""), AMBIGUOUS)
        if member_id is None:
            unresolved += 1
            continue
        if member_id not in resolved:
            resolved.append(member_id)
    return resolved, unresolved


def _week_and_date(value: Any) -> tuple[int | None, date | None]:
    """`week_or_date` is one field carrying either shape; split it into two columns."""
    if isinstance(value, bool) or value is None:
        return None, None
    if isinstance(value, int):
        return value, None
    text = str(value).strip()
    if text.isdigit():
        return int(text), None
    try:
        return None, date.fromisoformat(text[:10])
    except ValueError:
        return None, None


def _clean_asset(asset: dict[str, Any]) -> dict[str, Any] | None:
    kind = asset.get("kind")
    if kind == "player":
        return {key: asset.get(key) for key in PLAYER_FIELDS}
    if kind == "faab":
        return {key: asset.get(key) for key in FAAB_FIELDS}
    if kind == "condition" and asset.get("label") in CONDITION_LABELS:
        return {"kind": "condition", "label": asset["label"]}
    return None


def catalog_row(
    record: dict[str, Any],
    index: dict[str, int | None],
    season_id: int | None,
    loaded_at: datetime,
) -> CatalogRow:
    """Build one public row from one classification record."""
    picked = {key: record.get(key) for key in CATALOG_FIELDS}
    week, occurred_on = _week_and_date(picked["week_or_date"])
    parties = list(picked["parties"] or [])
    member_ids, unresolved = resolve_parties(parties, index)
    assets = [cleaned for asset in (picked["assets"] or []) if (cleaned := _clean_asset(asset))]
    confidence = picked["confidence"] if picked["confidence"] in CONFIDENCE_VALUES else "low"
    return CatalogRow(
        catalog_id=str(picked["id"]),
        season=int(picked["season"]),
        season_id=season_id,
        week=week,
        occurred_on=occurred_on,
        trade_type=str(picked["type"] or "trade"),
        structure=str(picked["structure"] or "unknown"),
        party_member_ids=member_ids,
        party_count=len(parties),
        assets=assets,
        faab_total=picked["faab_total"],
        confidence=confidence,
        unresolved_parties=unresolved,
        loaded_at=loaded_at,
    )
```

- [ ] **Step 4: Write the command**

```python
# packages/league-automation/src/ultimate_guillotine/cli/history.py
"""`ug history` subcommands: load-catalog, load-results.

Both are operator commands Ben runs on the Mac mini, and both print counts and
nothing else. The inputs name real people -- the classification file's parties and
the records workbook's winners -- so a loader that echoed a row back would put a
league member's name in a terminal scrollback and, worse, teach the next command
that doing so is normal.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from ultimate_guillotine.cli.deps import build_deps
from ultimate_guillotine.data.repositories import MemberAliasRepository
from ultimate_guillotine.history.catalog import build_label_index, catalog_row
from ultimate_guillotine.history.repository import HistoryRepository


def register(subparsers) -> None:
    parser = subparsers.add_parser("history", help="league history loaders")
    history_sub = parser.add_subparsers(dest="command", required=True)

    catalog = history_sub.add_parser("load-catalog", help="load the private trade classification")
    catalog.add_argument("path")
    catalog.set_defaults(handler=cmd_load_catalog)

    results = history_sub.add_parser("load-results", help="load season results from the workbook")
    results.add_argument("path")
    results.add_argument(
        "--notes", action="append", default=[], metavar="SEASON=TEXT",
        help="public commissioner note for a season; repeatable",
    )
    results.set_defaults(handler=cmd_load_results)


def cmd_load_catalog(args: argparse.Namespace) -> int:
    """Upsert every classification record into public.trade_catalog.

    Unresolved parties are counted rather than guessed: Ben adds an alias with
    `ug members aliases load` and reruns, and the count drops. Exit 1 only when
    nothing loaded at all, which means the file is for another league or the
    members table has not been synced.
    """
    deps = build_deps()
    repo = HistoryRepository(deps.conn)
    index = build_label_index(MemberAliasRepository(deps.conn).all_members())
    document = json.loads(Path(args.path).read_text(encoding="utf-8"))
    records = document.get("trades", document if isinstance(document, list) else [])
    loaded_at = datetime.now(UTC)

    season_ids: dict[int, int | None] = {}
    inserted = updated = unresolved = 0
    for record in records:
        season = int(record["season"])
        if season not in season_ids:
            season_ids[season] = repo.season_id_for(season)
        row = catalog_row(record, index, season_ids[season], loaded_at)
        outcome = repo.upsert_catalog(row)
        inserted += outcome == "inserted"
        updated += outcome == "updated"
        unresolved += row.unresolved_parties
    deps.conn.commit()

    print(f"catalog: {inserted} rows, {updated} updated, {unresolved} unresolved parties")
    return 1 if inserted == 0 and updated == 0 else 0
```

Register the group in `packages/league-automation/src/ultimate_guillotine/cli/main.py`:

```python
from ultimate_guillotine.cli import history, ingest, listener, members, ops, sleeper, targets, trades
...
    for module in (ops, targets, sleeper, ingest, listener, trades, members, history):
```

- [ ] **Step 5: Write the command test**

```python
# packages/league-automation/tests/cli/test_history.py
"""Command wiring and the counts-only contract."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ultimate_guillotine.cli import history as history_cli

#: Every word the two commands are allowed to print. A member name, a player name or a
#: line of chat would all fail this, which is the point.
ALLOWED_WORDS = {"catalog", "rows", "updated", "unresolved", "parties", "results",
                 "seasons", "names", "skipped"}


def _assert_counts_only(text: str) -> None:
    for word in re.findall(r"[A-Za-z][A-Za-z'-]*", text):
        assert word in ALLOWED_WORDS, f"unexpected word in loader output: {word}"


def test_history_help_lists_commands() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ultimate_guillotine.cli.main", "history", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    for name in ("load-catalog", "load-results"):
        assert name in result.stdout


class FakeRepo:
    def __init__(self, conn) -> None:
        self.rows = []

    def season_id_for(self, year: int) -> int | None:
        return None

    def upsert_catalog(self, row) -> str:
        self.rows.append(row)
        return "inserted"


def test_load_catalog_prints_counts_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "classification.json"
    path.write_text(json.dumps({"trades": [{
        "id": "2025-001", "season": 2025, "week_or_date": 3, "type": "trade",
        "structure": "1-for-1", "parties": ["Nobody"], "assets": [], "confidence": "high",
        "notes": "SENTINEL", "source_texts": ["SENTINEL"],
    }]}))
    conn = SimpleNamespace(commit=lambda: None)
    monkeypatch.setattr(history_cli, "build_deps", lambda: SimpleNamespace(conn=conn))
    monkeypatch.setattr(history_cli, "HistoryRepository", FakeRepo)
    monkeypatch.setattr(history_cli, "MemberAliasRepository",
                        lambda conn: SimpleNamespace(all_members=lambda: []))

    exit_code = history_cli.cmd_load_catalog(argparse.Namespace(path=str(path)))

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "catalog: 1 rows, 0 updated, 1 unresolved parties" in out
    assert "SENTINEL" not in out
    _assert_counts_only(out)


def test_load_catalog_exits_1_when_nothing_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({"trades": []}))
    conn = SimpleNamespace(commit=lambda: None)
    monkeypatch.setattr(history_cli, "build_deps", lambda: SimpleNamespace(conn=conn))
    monkeypatch.setattr(history_cli, "HistoryRepository", FakeRepo)
    monkeypatch.setattr(history_cli, "MemberAliasRepository",
                        lambda conn: SimpleNamespace(all_members=lambda: []))

    assert history_cli.cmd_load_catalog(argparse.Namespace(path=str(path))) == 1
    _assert_counts_only(capsys.readouterr().out)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/history/test_catalog.py packages/league-automation/tests/cli/test_history.py -v`
Expected: PASS, 7 tests. `test_load_results` cases are added in Task 4 — the `load-results` handler exists only as a name until then, so run `pytest -k "not load_results"` if the collection complains.

- [ ] **Step 7: Commit**

```bash
git add packages/league-automation/src/ultimate_guillotine/history/catalog.py \
        packages/league-automation/src/ultimate_guillotine/cli/history.py \
        packages/league-automation/src/ultimate_guillotine/cli/main.py \
        packages/league-automation/tests/history/test_catalog.py \
        packages/league-automation/tests/cli/test_history.py
git commit -m "feat: add ug history load-catalog with a private-field allowlist"
```

---

### Task 4: The records workbook reader and `ug history load-results`

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/history/records.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/history.py` (add `cmd_load_results`)
- Test: `packages/league-automation/tests/history/test_records.py`

**Interfaces:**
- Consumes: `HistoryRepository`, `SeasonResultRow`, `build_label_index`, openpyxl.
- Produces: `PUBLIC_SHEETS`, `read_winners(workbook) -> list[WinnerRow]`, `read_eliminations(workbook, season) -> list[dict]`, `season_result_rows(path, index, notes, loaded_at) -> tuple[list[SeasonResultRow], int]`, and `cmd_load_results(args) -> int`.

- [ ] **Step 1: Write the failing test**

```python
# packages/league-automation/tests/history/test_records.py
"""The workbook holds dues. These tests are the fence around that fact."""

from datetime import UTC, datetime
from pathlib import Path

from openpyxl import load_workbook

from ultimate_guillotine.history.catalog import build_label_index
from ultimate_guillotine.history.records import (
    PUBLIC_SHEETS,
    read_eliminations,
    read_winners,
    season_result_rows,
)

WORKBOOK = Path("history/league/ultimate-guillotine-records.xlsx")
LOADED_AT = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def test_public_sheets_exclude_the_dues_sheet() -> None:
    assert PUBLIC_SHEETS == ("Winners", "2023", "2024")
    assert "2025" not in PUBLIC_SHEETS


def test_no_value_from_the_dues_sheet_reaches_a_row() -> None:
    """The 2025 sheet is the roster-and-dues block. Nothing off it may appear in a row."""
    workbook = load_workbook(WORKBOOK, data_only=True)
    private_values = {
        str(cell).strip().lower()
        for row in workbook["2025"].iter_rows(values_only=True)
        for cell in row
        if cell is not None and str(cell).strip()
    }
    rows, _ = season_result_rows(WORKBOOK, index={}, notes={}, loaded_at=LOADED_AT)

    rendered = repr(rows).lower()
    for value in private_values:
        if len(value) < 3:  # bare seat numbers collide with counts; the names are the risk
            continue
        assert value not in rendered, "a 2025-sheet value reached a public row"


def test_winners_reads_year_and_champion_columns() -> None:
    workbook = load_workbook(WORKBOOK, data_only=True)
    winners = read_winners(workbook)
    years = [winner.year for winner in winners]

    assert years == [2019, 2020, 2021, 2022, 2023, 2024]
    # Column D carries a second name for 2022 alone; every other row leaves it empty.
    assert [winner.year for winner in winners if winner.second_name] == [2022]
    assert all(winner.champion_name for winner in winners)


def test_eliminations_are_counts_with_no_member_id() -> None:
    workbook = load_workbook(WORKBOOK, data_only=True)
    entries = read_eliminations(workbook, 2024)

    assert entries, "the 2024 sheet carries a week grid"
    assert all(entry["member_id"] is None for entry in entries)
    assert [entry["order"] for entry in entries] == list(range(1, len(entries) + 1))
    assert {"week", "order", "member_id", "gulag_out", "pool_out", "remaining", "note"} == set(
        entries[0]
    )


def test_unresolved_champion_is_counted_not_named() -> None:
    rows, unresolved = season_result_rows(WORKBOOK, index={}, notes={}, loaded_at=LOADED_AT)
    by_season = {row.season: row for row in rows}

    assert unresolved > 0, "an empty label index resolves nobody"
    assert all(row.champion_member_id is None for row in rows)
    assert by_season[2024].unresolved_names >= 1
    assert by_season[2024].team_count == 19


def test_a_note_is_attached_to_its_season() -> None:
    rows, _ = season_result_rows(
        WORKBOOK, index={}, notes={2022: "co-champions"}, loaded_at=LOADED_AT
    )
    by_season = {row.season: row for row in rows}
    assert by_season[2022].notes == "co-champions"
    assert by_season[2023].notes is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/history/test_records.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ultimate_guillotine.history.records'`.

- [ ] **Step 3: Write the reader**

```python
# packages/league-automation/src/ultimate_guillotine/history/records.py
"""Read the records workbook's public sheets.

The workbook is also the commissioner's dues ledger: the 2025 sheet is a roster with
a `paid` column, and the 2023 sheet carries a signup block with handles and `paid`
below its week grid. This module never opens the 2025 sheet and reads the 2023 sheet
only above its signup block, so no cell of either can reach a public table.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from ultimate_guillotine.history.models import SeasonResultRow
from ultimate_guillotine.trades.names import normalize_name

#: The only sheets read. A sheet added to the workbook is invisible until this changes.
PUBLIC_SHEETS = ("Winners", "2023", "2024")

#: `Winners`: `year` in column B, `winner` in column C, an unlabelled second name in D.
WINNERS_FIRST_ROW = 3
WINNERS_YEAR_COL, WINNERS_CHAMPION_COL, WINNERS_SECOND_COL = 2, 3, 4

#: `2024`: header at row 3, data from row 4. Week, Total Teams, Gulag Teams, Gen Pool Teams,
#: eliminated-from-Gulag, eliminated-from-Pool, Surviving Teams.
GRID_2024 = {"first_row": 4, "week": 2, "total": 3, "gulag_out": 6, "pool_out": 7, "remaining": 8}

#: `2023`: the second grid, rows 17-23. Week, Total Teams, Teams in Gulag, Teams sent to Gulag,
#: Teams cut at EOW, Teams going into next week. Rows below 24 are the signup block and are
#: never touched.
GRID_2023 = {"first_row": 17, "last_row": 23, "week": 13, "total": 14,
             "gulag_out": 17, "remaining": 18}


@dataclass(frozen=True)
class WinnerRow:
    year: int
    champion_name: str
    second_name: str | None


def _int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def read_winners(workbook) -> list[WinnerRow]:
    """Every row of the `Winners` sheet, oldest first."""
    sheet = workbook["Winners"]
    winners: list[WinnerRow] = []
    for row in range(WINNERS_FIRST_ROW, sheet.max_row + 1):
        year = _int(sheet.cell(row=row, column=WINNERS_YEAR_COL).value)
        champion = sheet.cell(row=row, column=WINNERS_CHAMPION_COL).value
        if year is None or not champion:
            continue
        second = sheet.cell(row=row, column=WINNERS_SECOND_COL).value
        winners.append(
            WinnerRow(year, str(champion).strip(), str(second).strip() if second else None)
        )
    return winners


def read_eliminations(workbook, season: int) -> list[dict]:
    """The season's week grid as ordered count entries.

    Both sheets record how many teams went out, never which -- so `member_id` is null
    for every entry here, and the page renders counts. Named entries arrive later from
    the Adjudicator, for 2026 onwards.
    """
    name = str(season)
    if name not in PUBLIC_SHEETS or name not in workbook.sheetnames:
        return []
    grid = GRID_2024 if season == 2024 else GRID_2023
    sheet = workbook[name]
    last_row = grid.get("last_row", sheet.max_row)
    entries: list[dict] = []
    week = None
    for row in range(grid["first_row"], last_row + 1):
        week = _int(sheet.cell(row=row, column=grid["week"]).value) or week
        gulag_out = _int(sheet.cell(row=row, column=grid["gulag_out"]).value)
        pool_out = _int(sheet.cell(row=row, column=grid["pool_out"]).value) if "pool_out" in grid else None
        remaining = _int(sheet.cell(row=row, column=grid["remaining"]).value)
        if week is None or (gulag_out is None and pool_out is None and remaining is None):
            continue
        entries.append({
            "week": week, "order": len(entries) + 1, "member_id": None,
            "gulag_out": gulag_out, "pool_out": pool_out, "remaining": remaining, "note": None,
        })
        week = week + 1 if season == 2024 else week
    return entries


def _team_count(workbook, season: int) -> int | None:
    grid = GRID_2024 if season == 2024 else GRID_2023
    name = str(season)
    if name not in workbook.sheetnames:
        return None
    return _int(workbook[name].cell(row=grid["first_row"], column=grid["total"]).value)


def season_result_rows(
    path: Path | str,
    index: dict[str, int | None],
    notes: dict[int, str],
    loaded_at: datetime,
) -> tuple[list[SeasonResultRow], int]:
    """Build one row per season in `Winners`, plus the count of names nobody matched.

    A name that does not resolve leaves its column null and increments a count; the
    workbook's spelling is never stored, so an unresolved champion is a number Ben can
    fix with an alias rather than a name sitting in a public table.
    """
    workbook = load_workbook(path, data_only=True, read_only=True)
    rows: list[SeasonResultRow] = []
    unresolved_total = 0
    for winner in read_winners(workbook):
        champion_id = index.get(normalize_name(winner.champion_name))
        second_id = index.get(normalize_name(winner.second_name)) if winner.second_name else None
        unresolved = int(champion_id is None) + int(winner.second_name is not None and second_id is None)
        unresolved_total += unresolved
        rows.append(SeasonResultRow(
            season=winner.year,
            season_id=None,
            champion_member_id=champion_id,
            # Open question 1: column D is loaded as a co-champion until Ben says otherwise.
            co_champion_member_id=second_id,
            runner_up_member_id=None,
            third_member_id=None,
            team_count=_team_count(workbook, winner.year),
            eliminations=read_eliminations(workbook, winner.year),
            notes=notes.get(winner.year),
            unresolved_names=unresolved,
            loaded_at=loaded_at,
        ))
    return rows, unresolved_total
```

- [ ] **Step 4: Write the command**

Append to `packages/league-automation/src/ultimate_guillotine/cli/history.py`:

```python
def _parse_notes(pairs: list[str]) -> dict[int, str]:
    """`--notes 2022=co-champions` into `{2022: "co-champions"}`."""
    notes: dict[int, str] = {}
    for pair in pairs:
        season, _, text = pair.partition("=")
        if not text.strip() or not season.strip().isdigit():
            raise SystemExit("--notes takes SEASON=TEXT")
        notes[int(season.strip())] = text.strip()
    return notes


def cmd_load_results(args: argparse.Namespace) -> int:
    """Upsert one public.season_results row per season in the workbook's Winners sheet."""
    deps = build_deps()
    repo = HistoryRepository(deps.conn)
    index = build_label_index(MemberAliasRepository(deps.conn).all_members())
    rows, unresolved = season_result_rows(
        Path(args.path), index, _parse_notes(args.notes), datetime.now(UTC)
    )
    seasons = 0
    for row in rows:
        stored = replace(row, season_id=repo.season_id_for(row.season))
        repo.upsert_season_result(stored)
        seasons += 1
    deps.conn.commit()

    print(f"results: {seasons} seasons, {unresolved} unresolved names")
    return 1 if seasons == 0 else 0
```

with these imports added at the top of the module:

```python
from dataclasses import replace

from ultimate_guillotine.history.records import season_result_rows
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/history packages/league-automation/tests/cli/test_history.py -v`
Expected: PASS — 6 records tests, 5 catalog tests, 3 CLI tests, 3 repository tests.

- [ ] **Step 6: Lint and commit**

```bash
uv run --project packages/league-automation ruff check packages/league-automation
git add packages/league-automation/src/ultimate_guillotine/history/records.py \
        packages/league-automation/src/ultimate_guillotine/cli/history.py \
        packages/league-automation/tests/history/test_records.py
git commit -m "feat: add ug history load-results reading only the workbook's public sheets"
```

---

### Task 5: Database types, query keys and fetchers

**Files:**
- Modify: `apps/web/src/board/types.ts` (four tables added to `Database`), `apps/web/src/board/boardClient.ts` (comment only)
- Create: `apps/web/src/history/types.ts`, `apps/web/src/history/queryKeys.ts`, `apps/web/src/history/fetchers.ts`
- Test: `apps/web/src/history/fetchers.test.ts`

**Interfaces:**
- Consumes: `boardClient` and `Database` from `src/board/`.
- Produces: `historyKeys`, `fetchTradeCatalog`, `fetchRegisteredTrades`, `fetchSeasonResults`, `fetchHistoryMembers`, and the row types `TradeCatalogRow`, `RegisteredTradeRow`, `SeasonResultRow`, `HistoryMemberRow`.

- [ ] **Step 1: Write the failing test**

```ts
// apps/web/src/history/fetchers.test.ts
/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";

import type { HistoryClient } from "./fetchers";
import {
  fetchRegisteredTrades,
  fetchSeasonResults,
  fetchTradeCatalog,
} from "./fetchers";

interface Call {
  table: string;
  columns: string;
  order?: [string, boolean];
}

function createFakeClient(responses: Record<string, unknown[]>): {
  client: HistoryClient;
  calls: Call[];
} {
  const calls: Call[] = [];
  const client = {
    from(table: string) {
      const call: Call = { table, columns: "" };
      calls.push(call);
      const builder = {
        select(columns: string) {
          call.columns = columns;
          return builder;
        },
        order(column: string, options: { ascending: boolean }) {
          call.order = [column, options.ascending];
          return builder;
        },
        then(resolve: (value: { data: unknown[]; error: null }) => unknown) {
          return Promise.resolve(resolve({ data: responses[table] ?? [], error: null }));
        },
      };
      return builder;
    },
  } as unknown as HistoryClient;
  return { client, calls };
}

describe("fetchTradeCatalog", () => {
  it("selects the catalog columns newest first", async () => {
    const { client, calls } = createFakeClient({ trade_catalog: [] });
    await fetchTradeCatalog(client);
    expect(calls[0].table).toBe("trade_catalog");
    expect(calls[0].columns).toContain("party_member_ids");
    expect(calls[0].order).toEqual(["season", false]);
  });
});

describe("fetchRegisteredTrades", () => {
  it("never selects the whole terms document", async () => {
    // `terms` carries `evidence_excerpt` -- verbatim chat -- and Sleeper usernames.
    const { client, calls } = createFakeClient({ trades: [] });
    await fetchRegisteredTrades(client);
    expect(calls[0].columns).not.toMatch(/(^|,)\s*terms\s*(,|$)/);
    expect(calls[0].columns).not.toContain("evidence_excerpt");
    expect(calls[0].columns).toContain("seasons ( year )");
  });
});

describe("fetchSeasonResults", () => {
  it("selects season results newest first", async () => {
    const { client, calls } = createFakeClient({ season_results: [] });
    await fetchSeasonResults(client);
    expect(calls[0].table).toBe("season_results");
    expect(calls[0].order).toEqual(["season", false]);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm --filter @ultimate-guillotine/web test -- src/history/fetchers.test.ts`
Expected: FAIL — `Failed to resolve import "./fetchers"`.

- [ ] **Step 3: Extend the `Database` type**

In `apps/web/src/board/types.ts`, inside `Database["public"]["Tables"]`, add:

```ts
      trade_catalog: ReadOnlyTable<{
        id: number;
        catalog_id: string;
        season: number;
        week: number | null;
        occurred_on: string | null;
        trade_type: string;
        structure: string;
        party_member_ids: number[];
        party_count: number;
        assets: Json;
        faab_total: number | null;
        confidence: "high" | "medium" | "low";
        source: "catalog" | "registered";
        unresolved_parties: number;
        loaded_at: string;
      }>;
      season_results: ReadOnlyTable<{
        id: number;
        season: number;
        champion_member_id: number | null;
        co_champion_member_id: number | null;
        runner_up_member_id: number | null;
        third_member_id: number | null;
        team_count: number | null;
        eliminations: Json;
        notes: string | null;
        unresolved_names: number;
        loaded_at: string;
      }>;
      trades: ReadOnlyTable<{
        id: number;
        season_id: number;
        trade_code: string;
        current_revision_id: number | null;
        status: "accepted" | "rescinded";
      }>;
      /**
       * `terms` is deliberately typed `Json` and never selected whole: it carries
       * `evidence_excerpt` (verbatim league chat) and `parties[].display_name` (the bare
       * Sleeper username). The history fetchers select JSON paths out of it instead.
       */
      trade_revisions: ReadOnlyTable<{
        id: number;
        trade_id: number;
        revision: number;
        terms: Json;
        effective_week: number | null;
      }>;
```

and change the closing comment of `apps/web/src/board/boardClient.ts` to read:

```ts
/**
 * `supabaseClient.ts` exports an untyped client. This is the app's typed view of it, shared by
 * `src/board` and `src/history`; the `Database` type covers every table the public pages read.
 */
```

- [ ] **Step 4: Write the keys and the fetchers**

```ts
// apps/web/src/history/queryKeys.ts
/** Query keys for the two history pages. Every key starts with `"history"`. */
export const historyKeys = {
  all: ["history"] as const,
  catalog: () => ["history", "trade_catalog"] as const,
  registered: () => ["history", "trades"] as const,
  revisions: () => ["history", "trade_revisions"] as const,
  seasonResults: () => ["history", "season_results"] as const,
  members: () => ["history", "members"] as const,
};
```

```ts
// apps/web/src/history/fetchers.ts
import type { SupabaseClient } from "@supabase/supabase-js";

import type { Database, TableRow } from "@/board/types";

export type HistoryClient = SupabaseClient<Database>;

export type TradeCatalogRow = TableRow<"trade_catalog">;
export type SeasonResultRow = TableRow<"season_results">;
export type HistoryMemberRow = Pick<
  TableRow<"members">,
  "id" | "sleeper_display_name" | "nickname"
>;

/** A registered trade with its season year embedded; `public.trades` has no year column. */
export interface RegisteredTradeRow {
  id: number;
  trade_code: string;
  status: "accepted" | "rescinded";
  current_revision_id: number | null;
  seasons: { year: number } | null;
}

/**
 * One current revision, read as JSON paths rather than as the whole `terms` document.
 * `terms.evidence_excerpt` is verbatim league chat and `terms.parties[].display_name` is the
 * bare Sleeper username; both are anon-readable today, and selecting them here would put them
 * on a public page. Only these three paths are ever requested.
 */
export interface RegisteredRevisionRow {
  id: number;
  trade_id: number;
  effective_week: number | null;
  kind: string | null;
  parties: unknown;
  assets: unknown;
}

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

const CATALOG_COLUMNS =
  "id, catalog_id, season, week, occurred_on, trade_type, structure, party_member_ids, " +
  "party_count, assets, faab_total, confidence, source, unresolved_parties, loaded_at";

export function fetchTradeCatalog(client: HistoryClient): Promise<TradeCatalogRow[]> {
  return unwrap<TradeCatalogRow>(
    client.from("trade_catalog").select(CATALOG_COLUMNS).order("season", { ascending: false }),
    "trade_catalog",
  );
}

export function fetchRegisteredTrades(client: HistoryClient): Promise<RegisteredTradeRow[]> {
  return unwrap<RegisteredTradeRow>(
    client
      .from("trades")
      .select("id, trade_code, status, current_revision_id, seasons ( year )")
      .order("id", { ascending: false }),
    "trades",
  );
}

export function fetchRegisteredRevisions(
  client: HistoryClient,
): Promise<RegisteredRevisionRow[]> {
  return unwrap<RegisteredRevisionRow>(
    client
      .from("trade_revisions")
      .select("id, trade_id, effective_week, kind:terms->>kind, parties:terms->parties, assets:terms->assets"),
    "trade_revisions",
  );
}

export function fetchSeasonResults(client: HistoryClient): Promise<SeasonResultRow[]> {
  return unwrap<SeasonResultRow>(
    client
      .from("season_results")
      .select(
        "id, season, champion_member_id, co_champion_member_id, runner_up_member_id, " +
          "third_member_id, team_count, eliminations, notes, unresolved_names, loaded_at",
      )
      .order("season", { ascending: false }),
    "season_results",
  );
}

export function fetchHistoryMembers(client: HistoryClient): Promise<HistoryMemberRow[]> {
  return unwrap<HistoryMemberRow>(
    client.from("members").select("id, sleeper_display_name, nickname"),
    "members",
  );
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pnpm --filter @ultimate-guillotine/web test -- src/history/fetchers.test.ts`
Expected: PASS, 3 tests.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/board/types.ts apps/web/src/board/boardClient.ts apps/web/src/history
git commit -m "feat: type and fetch the history tables without reading trade terms wholesale"
```

---

### Task 6: Derivations — merge, filter, stats

**Files:**
- Create: `apps/web/src/history/types.ts`, `apps/web/src/history/derive/merge.ts`, `apps/web/src/history/derive/filter.ts`, `apps/web/src/history/derive/stats.ts`
- Test: `apps/web/src/history/derive/merge.test.ts`, `filter.test.ts`, `stats.test.ts`

**Interfaces:**
- Consumes: the row types from Task 5, `resolveOwnerLabel` from `@/board/derive/join`.
- Produces: `CatalogTrade`, `TradeAsset`, `TradeFilters`, `normalizeRegisteredTrade`, `mergeTradeSources(catalog, registered, revisions, members) -> { trades: CatalogTrade[]; replacedByBackfill: number }`, `filterTrades(trades, filters) -> CatalogTrade[]`, `tradeStats(trades) -> TradeStats`.

- [ ] **Step 1: Write the failing tests**

```ts
// apps/web/src/history/derive/merge.test.ts
import { describe, expect, it } from "vitest";

import { mergeTradeSources, normalizeRegisteredTrade } from "./merge";

const MEMBERS = [
  { id: 1, nickname: "Alpha", sleeper_display_name: "alpha-user" },
  { id: 2, nickname: null, sleeper_display_name: "Bravo Display" },
];

const CATALOG_2024 = {
  id: 10, catalog_id: "2024-001", season: 2024, week: 3, occurred_on: null,
  trade_type: "trade", structure: "1-for-1", party_member_ids: [1, 2], party_count: 2,
  assets: [{ kind: "faab", amount: 5, from_party: 0, to_party: 1 }], faab_total: 5,
  confidence: "high" as const, source: "catalog" as const, unresolved_parties: 0,
  loaded_at: "2026-09-09T12:00:00Z",
};
const CATALOG_2025 = { ...CATALOG_2024, id: 11, catalog_id: "2025-001", season: 2025 };

const REGISTERED = {
  id: 5, trade_code: "T-2025-014", status: "accepted" as const,
  current_revision_id: 50, seasons: { year: 2025 },
};
const REVISION = {
  id: 50, trade_id: 5, effective_week: 4, kind: "rental",
  parties: [{ member_id: 1, display_name: "alpha-user" }, { member_id: 2 }],
  assets: [{ kind: "faab", amount: 12, from_member_id: 1, to_member_id: 2, player_id: null,
             player_name: null, unit: "faab", description: "SENTINEL PROSE" }],
};

describe("mergeTradeSources", () => {
  it("drops catalog rows for a season the backfill has registered, and counts them", () => {
    const { trades, replacedByBackfill } = mergeTradeSources(
      [CATALOG_2024, CATALOG_2025], [REGISTERED], [REVISION], MEMBERS,
    );
    const seasons = trades.map((trade) => `${trade.season}:${trade.sourceLabel}`);
    expect(seasons).toEqual(["2025:T-2025-014", "2024:catalog"]);
    expect(replacedByBackfill).toBe(1);
  });

  it("keeps catalog rows for a season with no registered trades", () => {
    const { trades, replacedByBackfill } = mergeTradeSources(
      [CATALOG_2024], [], [], MEMBERS,
    );
    expect(trades).toHaveLength(1);
    expect(replacedByBackfill).toBe(0);
  });

  it("labels owners by nickname, else Sleeper display name", () => {
    const { trades } = mergeTradeSources([CATALOG_2024], [], [], MEMBERS);
    expect(trades[0].parties.map((party) => party.label)).toEqual(["Alpha", "Bravo Display"]);
  });
});

describe("normalizeRegisteredTrade", () => {
  it("carries no free text out of the terms document", () => {
    const trade = normalizeRegisteredTrade(REGISTERED, REVISION, MEMBERS);
    expect(JSON.stringify(trade)).not.toContain("SENTINEL");
    expect(JSON.stringify(trade)).not.toContain("alpha-user");
    expect(trade.faabTotal).toBe(12);
    expect(trade.week).toBe(4);
    expect(trade.sourceLabel).toBe("T-2025-014");
  });

  it("marks a rescinded trade", () => {
    const trade = normalizeRegisteredTrade(
      { ...REGISTERED, status: "rescinded" }, REVISION, MEMBERS,
    );
    expect(trade.rescinded).toBe(true);
  });
});
```

```ts
// apps/web/src/history/derive/filter.test.ts
import { describe, expect, it } from "vitest";

import { filterTrades } from "./filter";
import type { CatalogTrade } from "../types";

const TRADE: CatalogTrade = {
  key: "catalog:1", season: 2025, week: 3, occurredOn: null, tradeType: "rental",
  structure: "player-for-faab", parties: [{ memberId: 1, label: "Alpha" }], partyCount: 2,
  assets: [{ kind: "player", playerId: "1", name: "A Player", position: "RB",
             fromParty: 0, toParty: 1 }],
  faabTotal: 12, confidence: "high", sourceLabel: "catalog", registered: false,
  rescinded: false, unresolvedParties: 1,
};

describe("filterTrades", () => {
  it("combines every filter with AND", () => {
    const other: CatalogTrade = { ...TRADE, key: "catalog:2", season: 2024, tradeType: "trade" };
    const trades = [TRADE, other];

    expect(filterTrades(trades, { season: 2025, type: null, position: null, memberId: null, search: "" }))
      .toEqual([TRADE]);
    expect(filterTrades(trades, { season: 2025, type: "trade", position: null, memberId: null, search: "" }))
      .toEqual([]);
    expect(filterTrades(trades, { season: null, type: null, position: "RB", memberId: 1, search: "play" }))
      .toEqual([TRADE, other]);
    expect(filterTrades(trades, { season: null, type: null, position: "QB", memberId: null, search: "" }))
      .toEqual([]);
  });

  it("matches the member filter against resolved parties only", () => {
    expect(filterTrades([TRADE], { season: null, type: null, position: null, memberId: 9, search: "" }))
      .toEqual([]);
  });
});
```

```ts
// apps/web/src/history/derive/stats.test.ts
import { describe, expect, it } from "vitest";

import { tradeStats } from "./stats";
import type { CatalogTrade } from "../types";

const base: CatalogTrade = {
  key: "k1", season: 2025, week: 1, occurredOn: null, tradeType: "trade", structure: "1-for-1",
  parties: [], partyCount: 2, assets: [], faabTotal: 10, confidence: "high",
  sourceLabel: "catalog", registered: false, rescinded: false, unresolvedParties: 0,
};

describe("tradeStats", () => {
  it("sums FAAB, counts seasons, and names the most-traded position", () => {
    const stats = tradeStats([
      { ...base, assets: [{ kind: "player", playerId: "1", name: "P", position: "RB",
                            fromParty: 0, toParty: 1 }] },
      { ...base, key: "k2", season: 2024, faabTotal: null,
        assets: [{ kind: "player", playerId: "2", name: "Q", position: "RB",
                   fromParty: 0, toParty: 1 },
                 { kind: "player", playerId: "3", name: "R", position: "WR",
                   fromParty: 1, toParty: 0 }] },
    ]);
    expect(stats).toEqual({ tradeCount: 2, seasonCount: 2, faabMoved: 10, topPosition: "RB" });
  });

  it("reports no position when nothing has one", () => {
    expect(tradeStats([base]).topPosition).toBeNull();
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pnpm --filter @ultimate-guillotine/web test -- src/history/derive`
Expected: FAIL — `Failed to resolve import "./merge"`.

- [ ] **Step 3: Write the domain types**

```ts
// apps/web/src/history/types.ts
export type Confidence = "high" | "medium" | "low";

export type TradeAsset =
  | { kind: "player"; playerId: string | null; name: string; position: string | null;
      fromParty: number | null; toParty: number | null }
  | { kind: "faab"; amount: number; fromParty: number | null; toParty: number | null }
  | { kind: "condition"; label: string };

export interface TradeParty {
  memberId: number;
  label: string;
}

/** One row on `/trades`, whether it came from the catalog or from a registered trade. */
export interface CatalogTrade {
  key: string;
  season: number;
  week: number | null;
  occurredOn: string | null;
  tradeType: string;
  structure: string;
  parties: TradeParty[];
  /** How many people were in the deal, including any the loader could not resolve. */
  partyCount: number;
  assets: TradeAsset[];
  faabTotal: number | null;
  confidence: Confidence;
  /** The trade code for a registered row, the literal `catalog` for a catalog row. */
  sourceLabel: string;
  registered: boolean;
  rescinded: boolean;
  unresolvedParties: number;
}

export interface TradeFilters {
  season: number | null;
  type: string | null;
  position: string | null;
  memberId: number | null;
  search: string;
}

export const EMPTY_FILTERS: TradeFilters = {
  season: null, type: null, position: null, memberId: null, search: "",
};

/** Parse a URL query value into a number, or null when it is absent or not a number. */
export function parseNumberParam(value: string | null): number | null {
  if (value === null || value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export interface SeasonElimination {
  week: number;
  order: number;
  memberId: number | null;
  gulagOut: number | null;
  poolOut: number | null;
  remaining: number | null;
  note: string | null;
}

export interface SeasonResult {
  season: number;
  championLabel: string | null;
  coChampionLabel: string | null;
  runnerUpLabel: string | null;
  thirdLabel: string | null;
  teamCount: number | null;
  eliminations: SeasonElimination[];
  notes: string | null;
  loadedAt: string;
}
```

- [ ] **Step 4: Write the derivations**

```ts
// apps/web/src/history/derive/merge.ts
import { resolveOwnerLabel } from "@/board/derive/join";

import type {
  RegisteredRevisionRow,
  RegisteredTradeRow,
  HistoryMemberRow,
  TradeCatalogRow,
} from "../fetchers";
import type { CatalogTrade, TradeAsset, TradeParty } from "../types";

export const CATALOG_SOURCE_LABEL = "catalog";

function labelFor(memberId: number, members: HistoryMemberRow[]): TradeParty {
  // `resolveOwnerLabel` takes `OwnerLabelSource | undefined` and answers "Unknown owner" for a
  // member it cannot label, so `find` returning undefined is already the right input.
  return { memberId, label: resolveOwnerLabel(members.find((m) => m.id === memberId)) };
}

function catalogAssets(value: unknown): TradeAsset[] {
  if (!Array.isArray(value)) return [];
  const assets: TradeAsset[] = [];
  for (const entry of value as Record<string, unknown>[]) {
    if (entry.kind === "player") {
      assets.push({
        kind: "player",
        playerId: (entry.sleeper_player_id as string) ?? null,
        name: (entry.name as string) ?? "",
        position: (entry.position as string) ?? null,
        fromParty: (entry.from_party as number) ?? null,
        toParty: (entry.to_party as number) ?? null,
      });
    } else if (entry.kind === "faab" && typeof entry.amount === "number") {
      assets.push({
        kind: "faab", amount: entry.amount,
        fromParty: (entry.from_party as number) ?? null,
        toParty: (entry.to_party as number) ?? null,
      });
    } else if (entry.kind === "condition" && typeof entry.label === "string") {
      assets.push({ kind: "condition", label: entry.label });
    }
  }
  return assets;
}

export function normalizeCatalogTrade(
  row: TradeCatalogRow,
  members: HistoryMemberRow[],
): CatalogTrade {
  return {
    key: `catalog:${row.id}`,
    season: row.season,
    week: row.week,
    occurredOn: row.occurred_on,
    tradeType: row.trade_type,
    structure: row.structure,
    parties: row.party_member_ids.map((id) => labelFor(id, members)),
    partyCount: row.party_count,
    assets: catalogAssets(row.assets),
    faabTotal: row.faab_total,
    confidence: row.confidence,
    sourceLabel: CATALOG_SOURCE_LABEL,
    registered: false,
    rescinded: false,
    unresolvedParties: row.unresolved_parties,
  };
}

/**
 * Turn a registered trade into the same shape, reading only the fields that are safe.
 *
 * The revision's `terms` document also holds `evidence_excerpt` — verbatim league chat — and
 * `parties[].display_name`, the bare Sleeper username. Neither is read here, and the fetcher
 * never requests them: this function takes ids and amounts and nothing else, so no wording
 * from the chat can reach the page even if a future terms shape adds more prose.
 */
export function normalizeRegisteredTrade(
  trade: RegisteredTradeRow,
  revision: RegisteredRevisionRow | undefined,
  members: HistoryMemberRow[],
): CatalogTrade {
  const rawParties = Array.isArray(revision?.parties)
    ? (revision.parties as { member_id?: number }[])
    : [];
  const memberIds = rawParties
    .map((party) => party.member_id)
    .filter((id): id is number => typeof id === "number");
  const rawAssets = Array.isArray(revision?.assets)
    ? (revision.assets as Record<string, unknown>[])
    : [];

  const assets: TradeAsset[] = [];
  let faabTotal: number | null = null;
  for (const asset of rawAssets) {
    if (asset.kind === "faab" && typeof asset.amount === "number") {
      faabTotal = (faabTotal ?? 0) + asset.amount;
      assets.push({
        kind: "faab", amount: asset.amount,
        fromParty: memberIds.indexOf(asset.from_member_id as number),
        toParty: memberIds.indexOf(asset.to_member_id as number),
      });
    } else if (asset.kind === "player") {
      assets.push({
        kind: "player",
        playerId: (asset.player_id as string) ?? null,
        name: (asset.player_name as string) ?? "",
        position: null,
        fromParty: memberIds.indexOf(asset.from_member_id as number),
        toParty: memberIds.indexOf(asset.to_member_id as number),
      });
    }
  }

  return {
    key: `registered:${trade.id}`,
    season: trade.seasons?.year ?? 0,
    week: revision?.effective_week ?? null,
    occurredOn: null,
    tradeType: revision?.kind ?? "trade",
    structure: `${memberIds.length}-team`,
    parties: memberIds.map((id) => labelFor(id, members)),
    partyCount: rawParties.length,
    assets,
    faabTotal,
    confidence: "high",
    sourceLabel: trade.trade_code,
    registered: true,
    rescinded: trade.status === "rescinded",
    unresolvedParties: rawParties.length - memberIds.length,
  };
}

/**
 * Union the two sources, newest season first.
 *
 * A season with at least one registered trade is the backfill's: its catalog rows are the same
 * deals read by an analyst rather than by the Registrar, so they drop out. The count of dropped
 * rows is returned rather than swallowed — the stats strip says so on the page.
 */
export function mergeTradeSources(
  catalog: TradeCatalogRow[],
  registered: RegisteredTradeRow[],
  revisions: RegisteredRevisionRow[],
  members: HistoryMemberRow[],
): { trades: CatalogTrade[]; replacedByBackfill: number } {
  const registeredSeasons = new Set(
    registered.map((trade) => trade.seasons?.year).filter((year): year is number => !!year),
  );
  const revisionById = new Map(revisions.map((revision) => [revision.id, revision]));

  const kept = catalog.filter((row) => !registeredSeasons.has(row.season));
  const trades = [
    ...registered.map((trade) =>
      normalizeRegisteredTrade(
        trade,
        trade.current_revision_id === null
          ? undefined
          : revisionById.get(trade.current_revision_id),
        members,
      ),
    ),
    ...kept.map((row) => normalizeCatalogTrade(row, members)),
  ].sort((a, b) => b.season - a.season || (b.week ?? 0) - (a.week ?? 0));

  return { trades, replacedByBackfill: catalog.length - kept.length };
}
```

```ts
// apps/web/src/history/derive/filter.ts
import type { CatalogTrade, TradeFilters } from "../types";

function matchesSearch(trade: CatalogTrade, term: string): boolean {
  const needle = term.trim().toLowerCase();
  if (needle === "") return true;
  return trade.assets.some(
    (asset) => asset.kind === "player" && asset.name.toLowerCase().includes(needle),
  );
}

/** Every filter is an AND. An absent filter (null, or an empty search) matches everything. */
export function filterTrades(trades: CatalogTrade[], filters: TradeFilters): CatalogTrade[] {
  return trades.filter((trade) => {
    if (filters.season !== null && trade.season !== filters.season) return false;
    if (filters.type !== null && trade.tradeType !== filters.type) return false;
    if (
      filters.position !== null &&
      !trade.assets.some(
        (asset) => asset.kind === "player" && asset.position === filters.position,
      )
    ) {
      return false;
    }
    if (
      filters.memberId !== null &&
      !trade.parties.some((party) => party.memberId === filters.memberId)
    ) {
      return false;
    }
    return matchesSearch(trade, filters.search);
  });
}

export function seasonOptions(trades: CatalogTrade[]): number[] {
  return [...new Set(trades.map((trade) => trade.season))].sort((a, b) => b - a);
}

export function typeOptions(trades: CatalogTrade[]): string[] {
  return [...new Set(trades.map((trade) => trade.tradeType))].sort();
}

export function positionOptions(trades: CatalogTrade[]): string[] {
  const positions = new Set<string>();
  for (const trade of trades) {
    for (const asset of trade.assets) {
      if (asset.kind === "player" && asset.position) positions.add(asset.position);
    }
  }
  return [...positions].sort();
}
```

```ts
// apps/web/src/history/derive/stats.ts
import type { CatalogTrade } from "../types";

export interface TradeStats {
  tradeCount: number;
  seasonCount: number;
  faabMoved: number;
  topPosition: string | null;
}

/** The strip under the filters. Computed over the filtered set, so it answers the view. */
export function tradeStats(trades: CatalogTrade[]): TradeStats {
  const seasons = new Set<number>();
  const positions = new Map<string, number>();
  let faabMoved = 0;

  for (const trade of trades) {
    seasons.add(trade.season);
    faabMoved += trade.faabTotal ?? 0;
    for (const asset of trade.assets) {
      if (asset.kind === "player" && asset.position) {
        positions.set(asset.position, (positions.get(asset.position) ?? 0) + 1);
      }
    }
  }

  let topPosition: string | null = null;
  let topCount = 0;
  // Ties break alphabetically, so the strip does not flicker between equal positions.
  for (const position of [...positions.keys()].sort()) {
    const count = positions.get(position) ?? 0;
    if (count > topCount) {
      topPosition = position;
      topCount = count;
    }
  }

  return { tradeCount: trades.length, seasonCount: seasons.size, faabMoved, topPosition };
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pnpm --filter @ultimate-guillotine/web test -- src/history`
Expected: PASS — 3 fetcher tests, 5 merge tests, 2 filter tests, 2 stats tests.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/history
git commit -m "feat: merge, filter and summarise catalog and registered trades"
```

---

### Task 7: The `/trades` page

**Files:**
- Create: `apps/web/src/history/useTradeCatalog.ts`, `apps/web/src/history/components/TradeCard.tsx`, `apps/web/src/history/components/TradeFilterBar.tsx`, `apps/web/src/history/components/StatsStrip.tsx`, `apps/web/src/app/trades/TradesPage.tsx`
- Test: `apps/web/src/history/components/TradeCard.test.tsx`, `apps/web/src/app/trades/TradesPage.test.tsx`

**Interfaces:**
- Consumes: `historyKeys`, the fetchers, `mergeTradeSources`, `filterTrades`, `tradeStats`, `boardClient`.
- Produces: `useTradeCatalog()` returning `{ trades, replacedByBackfill, loadedAt, isPending, errors }`, and `TradesPage`.

- [ ] **Step 1: Write the failing card test**

```tsx
// apps/web/src/history/components/TradeCard.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TradeCard } from "./TradeCard";
import type { CatalogTrade } from "../types";

const TRADE: CatalogTrade = {
  key: "catalog:1", season: 2024, week: 3, occurredOn: null, tradeType: "rental",
  structure: "player-for-faab",
  parties: [{ memberId: 1, label: "Alpha" }],
  partyCount: 2,
  assets: [
    { kind: "player", playerId: "1", name: "A Player", position: "RB", fromParty: 0, toParty: 1 },
    { kind: "faab", amount: 12, fromParty: 1, toParty: 0 },
    { kind: "condition", label: "rental" },
  ],
  faabTotal: 12, confidence: "low", sourceLabel: "catalog", registered: false,
  rescinded: false, unresolvedParties: 1,
};

describe("TradeCard", () => {
  it("names the resolved owner and counts the one it could not", () => {
    render(<TradeCard trade={TRADE} />);
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText(/and 1 unidentified owner/i)).toBeInTheDocument();
  });

  it("badges a low-confidence catalog row", () => {
    render(<TradeCard trade={TRADE} />);
    expect(screen.getByText(/low confidence/i)).toBeInTheDocument();
    expect(screen.getByText("catalog")).toBeInTheDocument();
  });

  it("shows the trade code for a registered row and strikes a rescinded one", () => {
    render(
      <TradeCard
        trade={{ ...TRADE, sourceLabel: "T-2025-014", registered: true, rescinded: true,
                 confidence: "high", unresolvedParties: 0 }}
      />,
    );
    expect(screen.getByText("T-2025-014")).toBeInTheDocument();
    expect(screen.getByRole("listitem")).toHaveAttribute("data-rescinded", "true");
    expect(screen.queryByText(/low confidence/i)).not.toBeInTheDocument();
  });

  it("expands to the asset list", () => {
    render(<TradeCard trade={TRADE} />);
    const toggle = screen.getByRole("button", { name: /rental/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("A Player")).toBeInTheDocument();
    expect(screen.getByText(/12 FAAB/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pnpm --filter @ultimate-guillotine/web test -- src/history/components/TradeCard.test.tsx`
Expected: FAIL — `Failed to resolve import "./TradeCard"`.

- [ ] **Step 3: Write the card**

```tsx
// apps/web/src/history/components/TradeCard.tsx
import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

import type { CatalogTrade } from "../types";

const FOCUS_RING_CLASS =
  "ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

function whenLabel(trade: CatalogTrade): string {
  if (trade.week !== null) return `${trade.season} · Week ${trade.week}`;
  if (trade.occurredOn !== null) return `${trade.season} · ${trade.occurredOn}`;
  return `${trade.season}`;
}

function assetLabel(asset: CatalogTrade["assets"][number]): string {
  if (asset.kind === "player") {
    return asset.position ? `${asset.name} (${asset.position})` : asset.name;
  }
  if (asset.kind === "faab") return `${asset.amount} FAAB`;
  return asset.label.replace(/_/g, " ");
}

export function TradeCard({ trade }: { trade: CatalogTrade }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const missing = Math.max(trade.partyCount - trade.parties.length, 0);

  return (
    <li data-rescinded={trade.rescinded} className="list-none">
      <Card className={cn(trade.rescinded && "opacity-60")}>
        <CardContent className="p-3">
          <Collapsible open={open} onOpenChange={setOpen}>
            <button
              type="button"
              onClick={() => setOpen((value) => !value)}
              aria-expanded={open}
              aria-controls={panelId}
              className={cn("flex w-full items-start justify-between gap-2 text-left", FOCUS_RING_CLASS)}
            >
              <span className="min-w-0">
                <span className="block text-xs text-muted-foreground">{whenLabel(trade)}</span>
                <span
                  className={cn(
                    "block truncate text-sm font-medium",
                    trade.rescinded && "line-through",
                  )}
                >
                  {trade.tradeType} · {trade.structure}
                </span>
              </span>
              <ChevronDown
                aria-hidden
                className={cn("mt-1 h-4 w-4 shrink-0 transition-transform", open && "rotate-180")}
              />
            </button>

            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {trade.parties.map((party) => (
                <Badge key={party.memberId} variant="secondary">
                  {party.label}
                </Badge>
              ))}
              {missing > 0 && (
                <span className="text-xs text-muted-foreground">
                  and {missing} unidentified owner{missing === 1 ? "" : "s"}
                </span>
              )}
              {trade.faabTotal !== null && <Badge variant="outline">{trade.faabTotal} FAAB</Badge>}
              {trade.confidence !== "high" && !trade.registered && (
                <Badge variant="outline">low confidence</Badge>
              )}
              {trade.rescinded && <Badge variant="destructive">rescinded</Badge>}
              <Badge variant={trade.registered ? "default" : "outline"}>{trade.sourceLabel}</Badge>
            </div>

            <CollapsibleContent id={panelId}>
              <ul className="mt-2 space-y-1 border-t pt-2">
                {trade.assets.map((asset, index) => (
                  <li key={`${asset.kind}-${index}`} className="text-sm">
                    {assetLabel(asset)}
                  </li>
                ))}
                {trade.assets.length === 0 && (
                  <li className="text-sm text-muted-foreground">No itemised assets recorded</li>
                )}
              </ul>
            </CollapsibleContent>
          </Collapsible>
        </CardContent>
      </Card>
    </li>
  );
}
```

- [ ] **Step 4: Write the hook, the filter bar, the stats strip and the page**

```ts
// apps/web/src/history/useTradeCatalog.ts
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { boardClient } from "@/board/boardClient";

import { mergeTradeSources } from "./derive/merge";
import {
  fetchHistoryMembers,
  fetchRegisteredRevisions,
  fetchRegisteredTrades,
  fetchTradeCatalog,
} from "./fetchers";
import { historyKeys } from "./queryKeys";

/** Both tables change by hand a few times a year; five minutes is generous, not stale. */
export const HISTORY_STALE_MS = 5 * 60 * 1000;

export function useTradeCatalog() {
  const catalog = useQuery({
    queryKey: historyKeys.catalog(),
    queryFn: () => fetchTradeCatalog(boardClient),
    staleTime: HISTORY_STALE_MS,
  });
  const registered = useQuery({
    queryKey: historyKeys.registered(),
    queryFn: () => fetchRegisteredTrades(boardClient),
    staleTime: HISTORY_STALE_MS,
  });
  const revisions = useQuery({
    queryKey: historyKeys.revisions(),
    queryFn: () => fetchRegisteredRevisions(boardClient),
    staleTime: HISTORY_STALE_MS,
  });
  const members = useQuery({
    queryKey: historyKeys.members(),
    queryFn: () => fetchHistoryMembers(boardClient),
    staleTime: HISTORY_STALE_MS,
  });

  const merged = useMemo(
    () =>
      mergeTradeSources(
        catalog.data ?? [], registered.data ?? [], revisions.data ?? [], members.data ?? [],
      ),
    [catalog.data, registered.data, revisions.data, members.data],
  );

  const loadedAt = useMemo(() => {
    const stamps = (catalog.data ?? []).map((row) => Date.parse(row.loaded_at));
    return stamps.length === 0 ? null : Math.max(...stamps);
  }, [catalog.data]);

  return {
    ...merged,
    loadedAt,
    members: members.data ?? [],
    isPending: catalog.isPending || registered.isPending || members.isPending,
    errors: [catalog.error, registered.error, revisions.error, members.error].filter(
      (error): error is Error => error instanceof Error,
    ),
  };
}
```

```tsx
// apps/web/src/history/components/StatsStrip.tsx
import type { TradeStats } from "../derive/stats";

export function StatsStrip({
  stats,
  replacedByBackfill,
}: {
  stats: TradeStats;
  replacedByBackfill: number;
}) {
  const cells: [string, string][] = [
    ["Trades", String(stats.tradeCount)],
    ["Seasons", String(stats.seasonCount)],
    ["FAAB moved", String(stats.faabMoved)],
    ["Most traded", stats.topPosition ?? "—"],
  ];
  return (
    <div>
      <dl className="grid grid-cols-4 gap-2 rounded-md border bg-card p-2 text-center">
        {cells.map(([label, value]) => (
          <div key={label}>
            <dt className="text-[11px] uppercase text-muted-foreground">{label}</dt>
            <dd className="text-sm font-medium">{value}</dd>
          </div>
        ))}
      </dl>
      {replacedByBackfill > 0 && (
        <p className="mt-1 text-xs text-muted-foreground">
          {replacedByBackfill} earlier catalog readings replaced by registered trades
        </p>
      )}
    </div>
  );
}
```

```tsx
// apps/web/src/history/components/TradeFilterBar.tsx
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import type { HistoryMemberRow } from "../fetchers";
import type { TradeFilters } from "../types";
import { resolveOwnerLabel } from "@/board/derive/join";

interface Props {
  filters: TradeFilters;
  seasons: number[];
  types: string[];
  positions: string[];
  members: HistoryMemberRow[];
  memberIds: number[];
  onChange: (next: Partial<TradeFilters>) => void;
  onClear: () => void;
}

export function TradeFilterBar(props: Props) {
  const { filters, seasons, types, positions, members, memberIds, onChange, onClear } = props;
  return (
    <div className="sticky top-0 z-10 space-y-2 bg-muted/40 pb-2 pt-1">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Season">
        {/* The vendored `Badge` is a plain div with no `asChild`, so a chip that must be
            clickable and focusable is a `Button` at `size="sm"`, not a Badge wrapping one. */}
        <Button
          type="button"
          size="sm"
          variant={filters.season === null ? "default" : "outline"}
          aria-pressed={filters.season === null}
          onClick={() => onChange({ season: null })}
        >
          All
        </Button>
        {seasons.map((season) => (
          <Button
            key={season}
            type="button"
            size="sm"
            variant={filters.season === season ? "default" : "outline"}
            aria-pressed={filters.season === season}
            onClick={() => onChange({ season })}
          >
            {season}
          </Button>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-2">
        <select
          aria-label="Type"
          className="h-9 rounded-md border bg-background px-2 text-sm"
          value={filters.type ?? ""}
          onChange={(event) => onChange({ type: event.target.value || null })}
        >
          <option value="">Any type</option>
          {types.map((type) => <option key={type} value={type}>{type}</option>)}
        </select>
        <select
          aria-label="Position"
          className="h-9 rounded-md border bg-background px-2 text-sm"
          value={filters.position ?? ""}
          onChange={(event) => onChange({ position: event.target.value || null })}
        >
          <option value="">Any position</option>
          {positions.map((position) => (
            <option key={position} value={position}>{position}</option>
          ))}
        </select>
        <select
          aria-label="Owner"
          className="h-9 rounded-md border bg-background px-2 text-sm"
          value={filters.memberId ?? ""}
          onChange={(event) =>
            onChange({ memberId: event.target.value ? Number(event.target.value) : null })
          }
        >
          <option value="">Any owner</option>
          {memberIds.map((id) => (
            <option key={id} value={id}>
              {resolveOwnerLabel(members.find((member) => member.id === id))}
            </option>
          ))}
        </select>
      </div>

      <div className={cn("flex gap-2")}>
        <Input
          aria-label="Search players"
          placeholder="Search players"
          value={filters.search}
          onChange={(event) => onChange({ search: event.target.value })}
        />
        <Button type="button" variant="outline" onClick={onClear}>Clear</Button>
      </div>
    </div>
  );
}
```

```tsx
// apps/web/src/app/trades/TradesPage.tsx
import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { formatUpdatedAt } from "@/board/derive/time";
import { positionOptions, seasonOptions, typeOptions } from "@/history/derive/filter";
import { filterTrades } from "@/history/derive/filter";
import { tradeStats } from "@/history/derive/stats";
import { StatsStrip } from "@/history/components/StatsStrip";
import { TradeCard } from "@/history/components/TradeCard";
import { TradeFilterBar } from "@/history/components/TradeFilterBar";
import { parseNumberParam, type TradeFilters } from "@/history/types";
import { useTradeCatalog } from "@/history/useTradeCatalog";

export function TradesPage() {
  const [params, setParams] = useSearchParams();
  const { trades, replacedByBackfill, loadedAt, members, isPending, errors } = useTradeCatalog();

  // Memoised on `params` rather than rebuilt each render: `filters` is a dependency of the
  // filter memo below, and `react-hooks/exhaustive-deps` is a warning that `--max-warnings 0`
  // turns into a failed lint.
  const filters: TradeFilters = useMemo(
    () => ({
      season: parseNumberParam(params.get("season")),
      type: params.get("type"),
      position: params.get("pos"),
      memberId: parseNumberParam(params.get("owner")),
      search: params.get("q") ?? "",
    }),
    [params],
  );

  function change(next: Partial<TradeFilters>) {
    const updated = new URLSearchParams(params);
    const mapping: [keyof TradeFilters, string][] = [
      ["season", "season"], ["type", "type"], ["position", "pos"],
      ["memberId", "owner"], ["search", "q"],
    ];
    for (const [key, param] of mapping) {
      if (!(key in next)) continue;
      const value = next[key];
      if (value === null || value === "") updated.delete(param);
      else updated.set(param, String(value));
    }
    setParams(updated, { replace: true });
  }

  const visible = useMemo(() => filterTrades(trades, filters), [trades, filters]);
  const stats = useMemo(() => tradeStats(visible), [visible]);
  const memberIds = useMemo(
    () => [...new Set(trades.flatMap((trade) => trade.parties.map((p) => p.memberId)))],
    [trades],
  );

  return (
    <section className="space-y-3">
      <TradeFilterBar
        filters={filters}
        seasons={seasonOptions(trades)}
        types={typeOptions(trades)}
        positions={positionOptions(trades)}
        members={members}
        memberIds={memberIds}
        onChange={change}
        onClear={() => setParams(new URLSearchParams(), { replace: true })}
      />
      <StatsStrip stats={stats} replacedByBackfill={replacedByBackfill} />

      {errors.map((error) => (
        <Alert key={error.message} variant="destructive">
          <AlertTitle>Could not load part of the catalog</AlertTitle>
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      ))}

      {isPending && (
        <div className="space-y-2">
          {[0, 1, 2].map((index) => <Skeleton key={index} className="h-20 w-full" />)}
        </div>
      )}

      {!isPending && trades.length === 0 && (
        <p className="rounded-md border bg-card p-4 text-sm">No trades loaded yet.</p>
      )}
      {!isPending && trades.length > 0 && visible.length === 0 && (
        <p className="rounded-md border bg-card p-4 text-sm">No trades match these filters.</p>
      )}

      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {visible.map((trade) => <TradeCard key={trade.key} trade={trade} />)}
      </ul>

      {loadedAt !== null && (
        <p className="text-xs text-muted-foreground">Loaded {formatUpdatedAt(loadedAt)}</p>
      )}
    </section>
  );
}
```

- [ ] **Step 5: Write the page test**

```tsx
// apps/web/src/app/trades/TradesPage.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TradesPage } from "./TradesPage";

const trades = vi.hoisted(() => ({ value: [] as unknown[] }));

vi.mock("@/history/useTradeCatalog", () => ({
  useTradeCatalog: () => ({
    trades: trades.value,
    replacedByBackfill: 1,
    loadedAt: Date.parse("2026-09-09T12:00:00Z"),
    members: [{ id: 1, nickname: "Alpha", sleeper_display_name: null }],
    isPending: false,
    errors: [],
  }),
}));

function renderPage(initialEntry = "/trades") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <TradesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  trades.value = [
    { key: "k1", season: 2025, week: 1, occurredOn: null, tradeType: "trade",
      structure: "1-for-1", parties: [{ memberId: 1, label: "Alpha" }], partyCount: 1,
      assets: [{ kind: "player", playerId: "1", name: "A Player", position: "RB",
                 fromParty: 0, toParty: 1 }],
      faabTotal: 4, confidence: "high", sourceLabel: "catalog", registered: false,
      rescinded: false, unresolvedParties: 0 },
    { key: "k2", season: 2024, week: 2, occurredOn: null, tradeType: "rental",
      structure: "player-for-faab", parties: [], partyCount: 2, assets: [], faabTotal: null,
      confidence: "high", sourceLabel: "catalog", registered: false, rescinded: false,
      unresolvedParties: 2 },
  ];
});

describe("TradesPage", () => {
  it("renders every trade and the stats strip", () => {
    renderPage();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("FAAB moved").nextSibling).toHaveTextContent("4");
    expect(screen.getByText(/1 earlier catalog readings replaced/)).toBeInTheDocument();
  });

  it("filters by the season in the URL", () => {
    renderPage("/trades?season=2024");
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText(/2024 · Week 2/)).toBeInTheDocument();
  });

  it("says so when a filter matches nothing", async () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Search players"), { target: { value: "zzz" } });
    expect(await screen.findByText("No trades match these filters.")).toBeInTheDocument();
  });

  it("shows the empty state when nothing is loaded", () => {
    trades.value = [];
    renderPage();
    expect(screen.getByText("No trades loaded yet.")).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pnpm --filter @ultimate-guillotine/web test -- src/history src/app/trades`
Expected: PASS — 4 card tests, 4 page tests, and the derive tests from Task 6 still green.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/history apps/web/src/app/trades
git commit -m "feat: add the public trade catalog page"
```

---

### Task 8: The `/history` page, the routes and the nav

**Files:**
- Create: `apps/web/src/history/useSeasonResults.ts`, `apps/web/src/history/components/SeasonCard.tsx`, `apps/web/src/history/components/WinnersStrip.tsx`, `apps/web/src/app/history/HistoryPage.tsx`
- Modify: `apps/web/src/router.tsx`, `apps/web/src/app/layout.tsx`
- Test: `apps/web/src/app/history/HistoryPage.test.tsx`, `apps/web/src/history/components/SeasonCard.test.tsx`

**Interfaces:**
- Consumes: `fetchSeasonResults`, `fetchHistoryMembers`, `resolveOwnerLabel`.
- Produces: `useSeasonResults()` returning `{ seasons: SeasonResult[]; loadedAt; isPending; errors }`, `SeasonCard`, `WinnersStrip`, `HistoryPage`, and the `/trades` and `/history` routes.

- [ ] **Step 1: Write the failing tests**

```tsx
// apps/web/src/history/components/SeasonCard.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SeasonCard } from "./SeasonCard";
import type { SeasonResult } from "../types";

const SEASON: SeasonResult = {
  season: 2024, championLabel: "Alpha", coChampionLabel: null, runnerUpLabel: null,
  thirdLabel: null, teamCount: 19,
  eliminations: [
    { week: 2, order: 1, memberId: null, gulagOut: 2, poolOut: 0, remaining: 17, note: null },
    { week: 3, order: 2, memberId: 7, gulagOut: null, poolOut: null, remaining: null, note: null },
  ],
  notes: "co-champions, tied on points", loadedAt: "2026-09-09T12:00:00Z",
};

describe("SeasonCard", () => {
  it("leads with the champion", () => {
    render(<SeasonCard season={SEASON} labelForMember={() => "Bravo"} />);
    expect(screen.getByText("Champion 2024")).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText(/19 teams/)).toBeInTheDocument();
    expect(screen.getByText("co-champions, tied on points")).toBeInTheDocument();
  });

  it("expands to counts, and to names where the data has them", () => {
    render(<SeasonCard season={SEASON} labelForMember={() => "Bravo"} />);
    const toggle = screen.getByRole("button", { name: /eliminations/i });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/2 out of the gulag, 0 from the pool, 17 remaining/)).toBeInTheDocument();
    expect(screen.getByText(/Bravo/)).toBeInTheDocument();
  });

  it("says when a champion could not be resolved", () => {
    render(
      <SeasonCard season={{ ...SEASON, championLabel: null }} labelForMember={() => "Bravo"} />,
    );
    expect(screen.getByText("Unrecorded owner")).toBeInTheDocument();
  });
});
```

```tsx
// apps/web/src/app/history/HistoryPage.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { HistoryPage } from "./HistoryPage";

const state = vi.hoisted(() => ({ seasons: [] as unknown[] }));

vi.mock("@/history/useSeasonResults", () => ({
  useSeasonResults: () => ({
    seasons: state.seasons,
    loadedAt: Date.parse("2026-09-09T12:00:00Z"),
    labelForMember: () => "Bravo",
    isPending: false,
    errors: [],
  }),
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><HistoryPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("HistoryPage", () => {
  it("shows the empty state when nothing is loaded", () => {
    state.seasons = [];
    renderPage();
    expect(screen.getByText("No seasons loaded yet.")).toBeInTheDocument();
  });

  it("lists the winners strip and one card per season, newest first", () => {
    state.seasons = [
      { season: 2024, championLabel: "Alpha", coChampionLabel: null, runnerUpLabel: null,
        thirdLabel: null, teamCount: 19, eliminations: [], notes: null,
        loadedAt: "2026-09-09T12:00:00Z" },
      { season: 2023, championLabel: "Bravo", coChampionLabel: null, runnerUpLabel: null,
        thirdLabel: null, teamCount: 20, eliminations: [], notes: null,
        loadedAt: "2026-09-09T12:00:00Z" },
    ];
    renderPage();
    const headings = screen.getAllByText(/Champion 20\d\d/);
    expect(headings.map((node) => node.textContent)).toEqual(["Champion 2024", "Champion 2023"]);
    expect(screen.getByRole("list", { name: /winners/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pnpm --filter @ultimate-guillotine/web test -- src/app/history src/history/components/SeasonCard.test.tsx`
Expected: FAIL — `Failed to resolve import "./SeasonCard"`.

- [ ] **Step 3: Write the hook and the components**

```ts
// apps/web/src/history/useSeasonResults.ts
import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { boardClient } from "@/board/boardClient";
import { resolveOwnerLabel } from "@/board/derive/join";

import { fetchHistoryMembers, fetchSeasonResults } from "./fetchers";
import { historyKeys } from "./queryKeys";
import type { SeasonElimination, SeasonResult } from "./types";
import { HISTORY_STALE_MS } from "./useTradeCatalog";

function toEliminations(value: unknown): SeasonElimination[] {
  if (!Array.isArray(value)) return [];
  return (value as Record<string, unknown>[]).map((entry, index) => ({
    week: Number(entry.week ?? 0),
    order: Number(entry.order ?? index + 1),
    memberId: typeof entry.member_id === "number" ? entry.member_id : null,
    gulagOut: typeof entry.gulag_out === "number" ? entry.gulag_out : null,
    poolOut: typeof entry.pool_out === "number" ? entry.pool_out : null,
    remaining: typeof entry.remaining === "number" ? entry.remaining : null,
    note: typeof entry.note === "string" ? entry.note : null,
  }));
}

export function useSeasonResults() {
  const results = useQuery({
    queryKey: historyKeys.seasonResults(),
    queryFn: () => fetchSeasonResults(boardClient),
    staleTime: HISTORY_STALE_MS,
  });
  const members = useQuery({
    queryKey: historyKeys.members(),
    queryFn: () => fetchHistoryMembers(boardClient),
    staleTime: HISTORY_STALE_MS,
  });

  const labelForMember = useCallback(
    (memberId: number | null): string | null => {
      if (memberId === null) return null;
      const member = (members.data ?? []).find((candidate) => candidate.id === memberId);
      return member ? resolveOwnerLabel(member) : null;
    },
    [members.data],
  );

  const seasons: SeasonResult[] = useMemo(
    () =>
      (results.data ?? []).map((row) => ({
        season: row.season,
        championLabel: labelForMember(row.champion_member_id),
        coChampionLabel: labelForMember(row.co_champion_member_id),
        runnerUpLabel: labelForMember(row.runner_up_member_id),
        thirdLabel: labelForMember(row.third_member_id),
        teamCount: row.team_count,
        eliminations: toEliminations(row.eliminations),
        notes: row.notes,
        loadedAt: row.loaded_at,
      })),
    [results.data, labelForMember],
  );

  const loadedAt = useMemo(() => {
    const stamps = seasons.map((season) => Date.parse(season.loadedAt));
    return stamps.length === 0 ? null : Math.max(...stamps);
  }, [seasons]);

  return {
    seasons,
    loadedAt,
    labelForMember,
    isPending: results.isPending || members.isPending,
    errors: [results.error, members.error].filter((error): error is Error => error instanceof Error),
  };
}
```

```tsx
// apps/web/src/history/components/SeasonCard.tsx
import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

import type { SeasonElimination, SeasonResult } from "../types";

export const UNRECORDED_OWNER = "Unrecorded owner";

const FOCUS_RING_CLASS =
  "ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2";

function eliminationText(
  entry: SeasonElimination,
  labelForMember: (memberId: number | null) => string | null,
): string {
  const named = labelForMember(entry.memberId);
  if (named !== null) return `Week ${entry.week} — ${named} eliminated`;
  const parts: string[] = [];
  if (entry.gulagOut !== null) parts.push(`${entry.gulagOut} out of the gulag`);
  if (entry.poolOut !== null) parts.push(`${entry.poolOut} from the pool`);
  if (entry.remaining !== null) parts.push(`${entry.remaining} remaining`);
  return `Week ${entry.week} — ${parts.join(", ")}`;
}

interface Props {
  season: SeasonResult;
  labelForMember: (memberId: number | null) => string | null;
}

export function SeasonCard({ season, labelForMember }: Props) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const runnerUps = [
    season.coChampionLabel && `Co-champion ${season.coChampionLabel}`,
    season.runnerUpLabel && `Runner-up ${season.runnerUpLabel}`,
    season.thirdLabel && `Third ${season.thirdLabel}`,
    season.teamCount !== null && `${season.teamCount} teams`,
  ].filter((part): part is string => Boolean(part));

  return (
    <li className="list-none">
      <Card>
        <CardContent className="space-y-2 p-4">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Champion {season.season}
          </p>
          <p className="text-2xl font-semibold">{season.championLabel ?? UNRECORDED_OWNER}</p>
          {runnerUps.length > 0 && (
            <p className="text-sm text-muted-foreground">{runnerUps.join(" · ")}</p>
          )}

          {season.eliminations.length > 0 && (
            <Collapsible open={open} onOpenChange={setOpen}>
              <button
                type="button"
                onClick={() => setOpen((value) => !value)}
                aria-expanded={open}
                aria-controls={panelId}
                className={cn("flex items-center gap-1 text-sm font-medium", FOCUS_RING_CLASS)}
              >
                Eliminations
                <ChevronDown
                  aria-hidden
                  className={cn("h-4 w-4 transition-transform", open && "rotate-180")}
                />
              </button>
              <CollapsibleContent id={panelId}>
                <ul className="mt-2 space-y-1 border-t pt-2 text-sm">
                  {season.eliminations.map((entry) => (
                    <li key={entry.order}>{eliminationText(entry, labelForMember)}</li>
                  ))}
                </ul>
              </CollapsibleContent>
            </Collapsible>
          )}

          {season.notes !== null && (
            <p className="text-sm text-muted-foreground">{season.notes}</p>
          )}
        </CardContent>
      </Card>
    </li>
  );
}
```

```tsx
// apps/web/src/history/components/WinnersStrip.tsx
import type { SeasonResult } from "../types";
import { UNRECORDED_OWNER } from "./SeasonCard";

export function WinnersStrip({ seasons }: { seasons: SeasonResult[] }) {
  return (
    <ul aria-label="Winners" className="divide-y rounded-md border bg-card text-sm">
      {seasons.map((season) => (
        <li key={season.season} className="flex justify-between px-3 py-1.5">
          <span className="text-muted-foreground">{season.season}</span>
          <span className="font-medium">{season.championLabel ?? UNRECORDED_OWNER}</span>
        </li>
      ))}
    </ul>
  );
}
```

```tsx
// apps/web/src/app/history/HistoryPage.tsx
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { formatUpdatedAt } from "@/board/derive/time";
import { SeasonCard } from "@/history/components/SeasonCard";
import { WinnersStrip } from "@/history/components/WinnersStrip";
import { useSeasonResults } from "@/history/useSeasonResults";

export function HistoryPage() {
  const { seasons, loadedAt, labelForMember, isPending, errors } = useSeasonResults();

  return (
    <section className="space-y-3">
      {errors.map((error) => (
        <Alert key={error.message} variant="destructive">
          <AlertTitle>Could not load the league history</AlertTitle>
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      ))}

      {isPending && <Skeleton className="h-40 w-full" />}

      {!isPending && seasons.length === 0 && (
        <p className="rounded-md border bg-card p-4 text-sm">No seasons loaded yet.</p>
      )}

      {seasons.length > 0 && (
        <>
          <WinnersStrip seasons={seasons} />
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {seasons.map((season) => (
              <SeasonCard key={season.season} season={season} labelForMember={labelForMember} />
            ))}
          </ul>
        </>
      )}

      {loadedAt !== null && (
        <p className="text-xs text-muted-foreground">Loaded {formatUpdatedAt(loadedAt)}</p>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Add the routes and the nav**

In `apps/web/src/router.tsx`, add two children **before** the `*` route (order matters — `*` matches everything):

```tsx
      {
        path: "trades",
        element: <TradesPage />,
      },
      {
        path: "history",
        element: <HistoryPage />,
      },
```

with `import { HistoryPage } from "@/app/history/HistoryPage";` and `import { TradesPage } from "@/app/trades/TradesPage";` at the top.

In `apps/web/src/app/layout.tsx`, replace the title row with the title, the nav, and the toggle:

```tsx
import { NavLink, Outlet } from "react-router-dom";

import { ModeToggle } from "@/components/mode-toggle";
import { cn } from "@/lib/utils";

/** The three public pages. `end` on `/` keeps the board link from matching every route. */
const LINKS: [string, string, boolean][] = [
  ["/", "Board", true],
  ["/trades", "Trades", false],
  ["/history", "History", false],
];

function App() {
  return (
    <div className="min-h-screen w-full bg-muted/40">
      <div className="mx-auto w-full max-w-6xl px-4 py-4">
        <div className="mb-2 flex items-center justify-between gap-3">
          <h1 className="text-lg font-semibold">Ultimate Guillotine</h1>
          <ModeToggle />
        </div>
        <nav aria-label="Pages" className="mb-3 flex gap-4 text-sm">
          {LINKS.map(([to, label, end]) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn("hover:underline", isActive ? "font-medium" : "text-muted-foreground")
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <Outlet />
      </div>
    </div>
  );
}

export default App;
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pnpm --filter @ultimate-guillotine/web test`
Expected: PASS — the whole suite, including the board's existing tests and the 3 season-card plus 2 history-page tests added here.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/history apps/web/src/app/history apps/web/src/router.tsx apps/web/src/app/layout.tsx
git commit -m "feat: add the league history page and nav between the three public pages"
```

---

### Task 9: Full verification

**Files:**
- No source changes expected. If a check fails, fix it where it points and re-run.

**Interfaces:**
- Consumes: everything from Tasks 1–8.
- Produces: a verified build, a loaded database, and a recorded manual check.

- [ ] **Step 1: Run every suite**

```bash
pnpm test:web
pnpm test:agents
pnpm lint
pnpm lint:agents
pnpm --filter @ultimate-guillotine/web build
supabase test db
```

Expected: all six succeed. `pnpm lint` runs with `--max-warnings 0`, so a single `react-refresh/only-export-components` warning fails it — if one appears, move the offending non-component export into a `.ts` file rather than disabling the rule. `tsc` typechecks the test files, so a drift between the `Database` type and a fixture fails at the build step.

- [ ] **Step 2: Load both tables on the Mac mini and read the counts**

```bash
ug history load-catalog data/private/analysis/trade-classification.json
ug history load-results history/league/ultimate-guillotine-records.xlsx
```

Expected: two count lines and nothing else. If `unresolved parties` or `unresolved names` is above zero, add the missing nicknames to the members JSON, run `ug members aliases load`, and rerun the loader — the counts should fall and no row should duplicate.

- [ ] **Step 3: Prove no dues and no chat text landed**

```bash
psql "$DATABASE_URL" -c "select count(*) from public.season_results where notes ilike '%paid%'"
psql "$DATABASE_URL" -c "select count(*) from public.trade_catalog t
  where t.assets::text ilike '%said%' or t.assets::text ilike '%🚨%'"
psql "$DATABASE_URL" -c "select jsonb_object_keys(a) from public.trade_catalog,
  lateral jsonb_array_elements(assets) a group by 1 order by 1"
```

Expected: the first two counts are `0`. The third lists only `kind`, `sleeper_player_id`, `name`, `position`, `amount`, `label`, `from_party`, `to_party` — any other key means the allowlist leaked and Task 3's `_clean_asset` is wrong.

- [ ] **Step 4: Manual check at 375 px**

```bash
pnpm dev
```

Open `http://localhost:5173/trades` with the device toolbar set to **375 × 812** and work through this list, noting each result in the commit message:

1. **Nav.** Board, Trades and History all appear under the title; the current page is the emphasised one; each link goes where it says and back.
2. **Single column.** Cards are full width and the page never scrolls horizontally.
3. **Filters in the URL.** Tap a season chip, choose a position, type a player name. The address bar gains `?season=…&pos=…&q=…`; reloading keeps the view; **Clear** empties both the filters and the query string.
4. **Stats strip.** The four figures change with the filters. If any season has registered trades, the "N earlier catalog readings replaced" line appears under the strip.
5. **Card expansion.** Tap a trade. The asset list opens in place, the chevron rotates, and tapping again collapses it.
6. **Owner labels.** Every party badge shows a nickname or a Sleeper display name. No bare Sleeper username appears anywhere. A trade with an unresolved party reads "and 1 unidentified owner".
7. **No chat text.** Expand several registered trades (those badged `T-…`). No sentence, quote, or emoji from the league chat appears on any card — only players, FAAB amounts and condition labels.
8. **`/history`.** The winners strip lists every season with its champion; each card leads with the champion under a `Champion <year>` eyebrow; the `Eliminations` panel opens to week rows.
9. **Both themes.** Toggle dark and light. No hard-coded colour shows through on either page.
10. **Empty and error states.** Filter to something impossible: "No trades match these filters." appears with the Clear button still reachable.
11. **No Realtime.** With the Network panel open and the page idle for two minutes, no new requests are issued and no WebSocket is opened. Switching to another tab and back issues one refetch (that is `refetchOnWindowFocus`, and it is intended).

Stop the dev server when finished.

- [ ] **Step 5: Record the verification**

```bash
git commit --allow-empty -m "chore: verify league history pages build, tests, loaders and 375px check

- pnpm test:web, test:agents, lint, lint:agents, build: pass
- supabase test db: pass, including league_history_pages.sql
- loaders run on the Mac mini; counts recorded, no names printed
- database check: no dues text, no chat text, asset keys within the allowlist
- manual 375px check: nav, single column, filters in URL, stats strip, expansion,
  owner labels, no chat text on registered cards, history cards, both themes,
  empty states, no realtime traffic"
```

- [ ] **Step 6: Open the pull request and confirm on the Vercel preview**

Push the branch and open a PR. On the Vercel preview URL, repeat steps 4.1, 4.3, 4.6, 4.7 and 4.8 at 375 px — nav, filters in the URL, owner labels, no chat text, and the history cards — so Ben reviews the deployed pages, as the spec's Done criteria require.

---

## Self-review

**Spec coverage.** Routes and nav → Task 8. Inputs, including the workbook column allowlist → Tasks 3 and 4. Both tables, RLS, policies, no `delete` grant → Task 1. Loader commands, counts-only output, idempotency, the field allowlist → Tasks 3 and 4. Merging catalog with registered trades → Task 6. Layout, filters, stats strip, season cards → Tasks 7 and 8. Freshness (no Realtime, five-minute `staleTime`), empty and error states → Tasks 7 and 8. Privacy → Global Constraints, enforced by tests in Tasks 3, 4, 5 and 6 and by the database checks in Task 9. Tests and rollout → every task's test step, plus Task 9. No spec section is left without a task.

**Placeholder scan.** No "TBD", no "add error handling", no "similar to Task N". Every code step carries the actual file content; every test step carries the actual assertions; every run step names the exact command and the expected result.

**Type consistency.** `CatalogRow` and `SeasonResultRow` (Task 2) are constructed only by `catalog_row` (Task 3) and `season_result_rows` (Task 4) and consumed only by `HistoryRepository` (Task 2). `CatalogTrade`, `TradeAsset`, `TradeParty`, `TradeFilters`, `SeasonResult` and `SeasonElimination` are declared once in `src/history/types.ts` (Task 6) and used unchanged in Tasks 7 and 8. `HistoryClient`, `TradeCatalogRow`, `RegisteredTradeRow`, `RegisteredRevisionRow`, `SeasonResultRow` and `HistoryMemberRow` are declared in `src/history/fetchers.ts` (Task 5) and imported by name thereafter. `HISTORY_STALE_MS` is defined once in `useTradeCatalog.ts` and imported by `useSeasonResults.ts`. `resolveOwnerLabel` is the board's existing export, not a reimplementation, and it is called with `OwnerLabelSource | undefined` — never `null`, which its signature rejects under `strict`.

**Repository APIs checked, not assumed.** `@testing-library/user-event` is **not** a dependency of `apps/web`; every interaction in this plan's tests uses `fireEvent`, as `src/app/board/BoardPage.test.tsx` does. The vendored `Badge` (`src/components/ui/badge.tsx`) is a plain `div` with no `asChild`, so clickable season chips are `Button`s. `Alert` exports `AlertTitle` and `AlertDescription`; `Skeleton`, `Collapsible` / `CollapsibleContent`, `Card` / `CardContent`, `Input` and `Button` all exist as imported. `react-hooks/exhaustive-deps` is a warning, and `--max-warnings 0` makes one fail the build, so every `useMemo` in Task 7 lists its real dependencies.

---

## Still open

1. **`public.trade_revisions.terms` is anon-readable and contains chat.** Spec issue 1: `evidence_excerpt` (a verbatim league message) and `parties[].display_name` (the Sleeper username) sit in a table `anon` may select, today, with or without these pages. This plan keeps them off the page but cannot un-publish them. The fix is a Registrar change — move the excerpt to `private.source_messages` only, or expose trades through a view that projects the safe fields — and belongs in its own spec. Flag it to Ben before `/trades` ships publicly.
2. **Column D of the `Winners` sheet** loads as `co_champion_member_id` (spec Open Question 1). If Ben says runner-up, it is one field name in `season_result_rows` and one label in `SeasonCard`.
3. **Low-confidence catalog rows** render with a badge (spec Open Question 3). Hiding them behind a toggle is one predicate in `filterTrades`.
