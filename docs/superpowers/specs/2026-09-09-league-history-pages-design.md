# League History Pages

## Purpose

Two public pages beside the board: a **trade catalog** at `/trades` — every deal the league has made,
filterable — and a **league history** at `/history` — who won each season and how each season burned
down. Both are read-only and unauthenticated, and they answer the two questions the board cannot:
what does this league do, and who has won. The spec follows the page conventions in
`2026-09-09-league-board-design.md`, takes owner labels from the columns
`2026-09-09-league-data-layer-design.md` publishes, and merges with the trades
`2026-09-09-league-history-backfill-design.md` will land in `public.trades` (all three in
`docs/superpowers/specs/`). It defines two tables and redefines none.

## Routes and Navigation

`apps/web/src/router.tsx` serves `BoardPage` at `/`, redirects `board` to `/`, and sends `*` home.
`/trades` and `/history` are inserted **before** the `*` redirect, and `App` in
`apps/web/src/app/layout.tsx` grows a three-item nav under the league title — Board, Trades, History
— marking the active route with `aria-current="page"`.

## Inputs

1. **`data/private/analysis/trade-classification.json`** (git-ignored, from the analyst pass), with
   records `{id, season, week_or_date, source, type, structure, parties, assets, faab_total,
   confidence, notes, source_texts}`, nicknames in `parties`, and `notes` / `source_texts`
   **private** — never loaded, never rendered, never copied out.
2. **`history/league/ultimate-guillotine-records.xlsx`**, sheets `Winners`, `2023`, `2024` only:
   - `Winners` rows 3–8: column B `year`, column C `winner`, column D — a second name present only
     for 2022 — read as a co-champion. Names resolve to member ids and are then discarded.
   - `2024`, header row 3: `Week`, `Total Teams`, `Gulag Teams`, `Gen Pool Teams`, the two "Teams
     Eliminated this week from" columns `Gulag` and `Pool`, `Surviving Teams`, `Winner`.
   - `2023`: the week grid at rows 3–7 (`Week`, `Safe`, `Gulag`, `Gladiator`, `Cut`, `Winner!`) and
     rows 16–24 (`Week`, `Total Teams`, `Teams in Gulag`, `Teams sent to Gulag`, `Teams cut at EOW`,
     `Teams going into next week`).
   - `2023` row 9, the upper grid's `Total` row: a team count only, read solely to check it against
     the summary grid's `Total Teams`; the season publishes a count only if the two agree.
   - **Never loaded, from any sheet:** the `paid` column — dues are private and stay private, the
     hard rule here — the 2025 roster block (seat number, first name, last name, `paid`, the
     replacement / `removed` columns), the 2023 signup block at rows 28–48 (names, three dated
     `y`/`n`/`m` columns, `sleeper signup` handles, `paid`), and the bye-week text. A fixed sheet
     allowlist enforces this.
3. **`public.trades` / `public.trade_revisions`**, read by `/trades` once the backfill or the live
   Registrar has written a season, plus `public.members` for owner labels and `public.seasons` for
   the years that have rows. None of the three is ever copied into the catalog table.

## Tables

Both in the existing shape: identity primary key, `created_at timestamptz not null default now()`,
RLS enabled, `revoke all` then `grant select` to `anon, authenticated` behind a `"Public <table> are
readable"` policy, and an `"Automation writes <table>"` policy `for all to automation_worker using
(true) with check (true)` with `select, insert, update` grants — no `delete` grant on either. One
migration, `supabase/migrations/<timestamp>_league_history_pages.sql`.

**`public.trade_catalog`.** `catalog_id text not null unique` (the analyst record's `id`, the natural
key reruns upsert on); `season int not null` plus `season_id bigint references public.seasons (id)`
— the plain year is the key, since the catalog outruns the seasons table; `week int` and
`occurred_on date`, at least one set; `trade_type text not null`; `structure text not
null`; `party_member_ids bigint[] not null default '{}'`; `party_count int not null`; `assets jsonb
not null default '[]'`; `faab_total int`; `confidence text not null check (confidence in
('high','medium','low'))`; `source text not null default 'catalog' check (source in
('catalog','registered'))`; `unresolved_parties int not null default 0`; `loaded_at timestamptz not
null`. Indexed on `season` and `trade_type`, GIN on `party_member_ids`. `assets` holds **public facts
only**, each entry one of three closed shapes: `{"kind":"player", "sleeper_player_id":string|null,
"name":string, "position":string|null, "from_party":int, "to_party":int}`, `{"kind":"faab",
"amount":int, "from_party":int, "to_party":int}`, or `{"kind":"condition", "label":string}` whose
label comes from a closed vocabulary (`rental`, `return_after_week`, `conditional`, `keeper`,
`two_way`) — a condition is a label, never prose, so no chat sentence rides in on a free-text
field.

**`public.season_results`.** `season int not null unique`; `season_id bigint references
public.seasons (id)`; `champion_member_id`, `co_champion_member_id`, `runner_up_member_id`,
`third_member_id`, each `bigint references public.members (id)`; `team_count int`; `eliminations
jsonb not null default '[]'`; `notes text` (public commissioner text, typed into the loader);
`unresolved_names int not null default 0`; `source text not null default 'records-xlsx'`;
`loaded_at timestamptz not null`. `eliminations` is ordered, one entry per week: `{"week":int,
"order":int, "member_id":int|null, "gulag_out":int|null, "pool_out":int|null, "remaining":int|null,
"note":string|null}` — named entries come from the Adjudicator's `league_events` for 2026 on, while
2023 and 2024 carry the workbook's counts with `member_id` null.

## Loader Commands

Two subcommands in a new `packages/league-automation/src/ultimate_guillotine/cli/history.py`,
registered in `cli/main.py` beside `members`, run by Ben on the Mac mini:

```
ug history load-catalog data/private/analysis/trade-classification.json
ug history load-results history/league/ultimate-guillotine-records.xlsx
```

Both follow `cli/members.py`: build deps, read the file, upsert, commit, print **counts only**, exit
non-zero only when nothing loaded. Neither ever prints a member name, a player name, a nickname, or a
line of source text — output is `catalog: 214 rows, 3 updated, 5 unresolved parties` and `results: 6
seasons, 6 updated, 2 unresolved names, 0 weeks with no count`. Both are idempotent, upserting on `catalog_id` and `season`.

`load-catalog` copies fields through an explicit **allowlist** — `id`, `season`, `week_or_date`,
`type`, `structure`, `parties`, `assets`, `faab_total`, `confidence` — not by deleting private fields
from a copied dict, so a field the analyst adds later is dropped by default. Nicknames
resolve through `MemberAliasRepository`; an unresolved party is counted, left out of
`party_member_ids`, and fixed with an alias on the next run. `load-results` resolves `Winners` names
the same way and takes `--notes SEASON=TEXT`. Both are operator-run; neither is a cron job.

## Merging the Catalog With Registered Trades

`/trades` runs two queries: all of `public.trade_catalog`, and `public.trades` joined to its current
`public.trade_revisions` row. A pure `mergeTradeSources` unions them: a season with **at least one**
row in `public.trades` is a **registered season**, so its registered rows show and its catalog rows
drop out, being the same deals read by an analyst rather than by the Registrar; the dropped count
shows in the stats strip as "N earlier catalog readings replaced". A season with no registered rows
shows its catalog rows. Every card carries a source badge — the trade code (`T-2025-014`) for a
registered row, a muted `catalog` chip otherwise — and a rescinded trade renders struck through. The
rule is page-side, not a migration, so a season switches over the day the backfill lands it.

## Layout, Freshness and Error States

375 px first, single column, semantic Tailwind tokens only, the existing `ThemeProvider`, and the
board's `Card`, `Badge`, `Collapsible`, `ToggleGroup` and `Input` primitives. Both pages are a `<ul>`
of `<li>` cards, every expand control is a real button with `aria-expanded`, and filter state lives in
the URL query string.

**`/trades`.** A sticky header with four filters — season chips, type, position, member (a select of
owner labels) — plus a player-name search, then a stats strip: trades shown, seasons covered, FAAB
moved, most-traded position. One card per trade: season and week-or-date, type and structure badges,
one row per party with the owner label and what that party gave, a FAAB chip, a `low confidence`
badge, and the source badge. Filters combine with AND: member matches `party_member_ids`, position
any `player` asset's position.

**`/history`.** A winners strip — one line per season, year and champion — then one card per season,
newest first, the champion as the headline under a small `Champion 2024` eyebrow with runner-up,
third and team count on a muted line below. An `Eliminations` collapsible holds week rows (`Week 4 —
2 out of the gulag, 1 from the pool, 14 remaining`, or the named form once the Adjudicator supplies
it); the `notes` line renders last.

**Realtime is not required and is not used**: both tables change a handful of times a year, by hand.
Queries use a five-minute `staleTime` plus `refetchOnWindowFocus` and no channel or polling; each
footer shows `Loaded <date>` from `max(loaded_at)` through the board's `formatUpdatedAt`. An empty
table renders "No trades loaded yet", a filter matching nothing shows a clear-filters button, and a
failed query shows the board's `Alert` pattern without blanking the rest. When a trade's
`party_count` is one owner short, the card says "and a former manager" — never a raw name.

## Privacy and Safety

- **No dues.** The `paid` columns are never read, stored, or rendered; the sheet allowlist and a test
  asserting no 2025-sheet value reaches the database enforce it.
- **No chat text.** `source_texts` and `notes` from the classification JSON are never loaded; the
  only free text in either table is `season_results.notes`, typed by Ben on the command line.
- **No usernames.** Neither table stores a person's name. Parties and champions are `members` ids,
  labelled `nickname` else `sleeper_display_name`, never `display_name`; unresolved is a count.
- **No private schema.** Both pages read only these two tables plus `members`, `seasons`,
  `players`, `trades`, `trade_revisions`; anon key, `select` only. `assets` names are NFL players.

## Test and Rollout

pgTAP in `supabase/tests/league_history_pages.sql`: both tables exist, RLS is on, `policies_are`
matches the two policies per table, `automation_worker` holds no `delete` on either, the checks
reject a bad `confidence` or `source`, and the natural-key uniques reject a duplicate. Python tests
against the local stack: an upsert rerun leaves one row with identical content; the allowlist drops
`notes` and `source_texts`, asserted with a sentinel string in those fields that must appear nowhere
in the table; an unresolved party is counted, not guessed; the workbook loader reads only the three
allowlisted sheets and writes no value appearing on the `2025` sheet; both print counts only. Web
tests with Vitest: `mergeTradeSources` hides and counts a registered season's catalog rows; filters
combine with AND; the stats strip sums FAAB; a season card renders counts when `member_id` is null.

Rollout is: migration, both loaders on the Mac mini, read the counts, deploy. Done means `/trades`
and `/history` render from Supabase only, the nav works in both directions,
`pnpm lint`, `pnpm test:web` and `pnpm test:agents` pass, no dues or chat text exists in either
table, and Ben has reviewed the Vercel preview at 375 px in light and dark.

## Out of Scope

- Any write path from the web app; both pages are read-only, unauthenticated, and add nothing to
  `public.trades`, the Registrar, or the backfill, which this spec only reads.
- Per-member pages, head-to-head records, and trade grades — the catalog states what happened.
- Weekly scores, rosters and gulag standings, realtime, and any cron job; only champions and counts.

## Open Questions for Ben

1. **Column D of the `Winners` sheet.** Only 2022 has a second name — co-champion or runner-up?
2. **Champions who have left.** 2019–2021 winners may have no `members` row — create one?
3. **Low-confidence rows.** Badge them, or hide them behind a "show uncertain" toggle?
4. **Position filter.** QB/RB/WR/TE, matching the board, or K and DEF too?
5. **How far back should `/trades` go?** The catalog may reach 2020; cap the page at 2023 instead?
6. **Elimination detail for 2023 and 2024.** Worth a later pass to name who went out each week?

## Decisions from Ben (2026-09-09)

- Answering question 2: a champion who has left the league gets a member profile that is not tied to Sleeper (`ug members former add`, keyed `former:<slug>` with the name as the nickname), and because the rest of the catalog's old nicknames will not be mapped one by one, every party these pages still cannot name reads as "a former manager" — on the trade cards, on the champion line and on a named elimination line — rather than as "unidentified owner" or "Unlisted"; the owner filter leaves them out entirely, since one such option would stand for every unmapped party at once.
