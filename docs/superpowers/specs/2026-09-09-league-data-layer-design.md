# League Data Layer

## Purpose

Make the Sleeper facts every downstream feature needs — who holds which player, in which lineup
slot, with how much FAAB, projected for how many points this week — first-class rows in Supabase
instead of browser-side Sleeper calls. The League board, Trade Advisor, League Concierge data
questions, and Game Pulse all read from this one layer, so they agree with each other and with the
bot, and so a Sleeper outage degrades everything the same way.

This layer uses the shared design in
`docs/superpowers/specs/2026-08-27-automation-foundation-design.md`. It defines tables; it defines
no agent, no message, and no language-model call. Other specs reference these tables by name and do
not redefine them.

## Trigger and Cadence

Three scheduled, script-only jobs in `hermes/guillotine/cron.yaml`, all invoking `ug` CLIs with no
model in the loop, all wrapped in `run_scheduled` so each records one `private.agent_runs` row and
dedupes a second fire inside the same UTC minute:

- `guillotine-sleeper-sync` (existing, `every 10m`, agent `sleeper-sync`) — extended to write
  rosters, team state, and the cached league settings alongside members and teams.
- `guillotine-sleeper-projections` (new, agent `projections-sync`) — baseline `*/30 * * * *`,
  plus three game-window entries at `*/5` sharing the same agent name so the per-minute
  idempotency key absorbs the overlap: `*/5 20-23 * * 4` (Thursday night), `*/5 13-23 * * 0`
  (Sunday), `*/5 20-23 * * 1` (Monday night). Cron fields are the Mac mini's local time
  (`America/New_York`); the manifest says so next to the entries.
- `guillotine-nfl-state` (new, `every 10m`, agent `nfl-state`) — refreshes one row from
  `get_nfl_state`.

Every week-scoped job reads `public.nfl_state` for the week rather than deriving one from the
clock. If that row is missing or its `synced_at` is older than 60 minutes, the job refreshes it
inline before continuing, so a stalled state job never silently pins the league to a stale week.

## Tables

All in the `public` schema, all following the existing pattern: identity primary key,
`created_at timestamptz not null default now()`, RLS enabled, `revoke all` then `grant select` to
`anon, authenticated` with a `"Public <table> are readable"` policy, and an
`"Automation writes <table>"` policy `for all to automation_worker using (true) with check (true)`
alongside the matching grants. One migration,
`supabase/migrations/<timestamp>_league_data_layer.sql`.

### `public.seasons` (extended, not replaced)

Four columns are added rather than creating a settings table: `scoring_settings jsonb not null
default '{}'`, `roster_positions jsonb not null default '[]'`, `waiver_budget int`, and
`league_synced_at timestamptz`. This is where the league's scoring settings are cached, refreshed
from `get_league().scoring_settings` on every 10-minute sync. `seasons.phase` stays the league's
own rules phase and is unrelated to `nfl_state.season_type`.

### `public.roster_holdings`

`season_id bigint not null references public.seasons (id)`, `team_id bigint not null references
public.teams (id)`, `sleeper_player_id text not null`, `slot text not null check (slot in
('starter', 'bench', 'ir', 'taxi'))`, `slot_index int`, `lineup_position text`,
`synced_at timestamptz not null`, `unique (season_id, team_id, sleeper_player_id)`, indexes on
`(season_id, sleeper_player_id)` and `team_id`.

Slots come straight from the Sleeper roster payload as Sleeper reports them: an id in `starters`
is `starter`, in `reserve` is `ir`, in `taxi` is `taxi`, and anything else in `players` is `bench`.
`slot_index` is the player's ordinal in the `starters` array and `lineup_position` is the label at
that index in `seasons.roster_positions` (`QB`, `RB`, `WR`, `TE`, `FLEX`, `SUPER_FLEX`, …).
Sleeper writes `"0"` into an unfilled starter slot; those produce no row, only a count (see
`team_week_projections.empty_slots`). There is deliberately no foreign key to `public.players`:
Sleeper rosters can carry ids the filtered skill-position directory drops.

This is a current-state cache, not a league fact, so it is the one public table where deletion is
correct — a dropped player must vanish. The migration grants `delete` on this table alone to
`automation_worker`; every other public table keeps the existing insert/update-only grant.

### `public.team_season_state`

`season_id`, `team_id`, `unique (season_id, team_id)`; `faab_budget int not null`,
`faab_used int not null`, `faab_remaining int generated always as (faab_budget - faab_used)
stored`; `wins int not null default 0`, `losses int not null default 0`, `ties int not null
default 0`, `points_for numeric(10,2) not null default 0`, `points_against numeric(10,2) not null
default 0`; `is_eliminated boolean not null default false`, `eliminated_week int`,
`elimination_source text check (elimination_source in ('adjudicator', 'sleeper_inferred',
'manual'))`, `state_version int not null default 1`, `synced_at timestamptz not null`.

`faab_budget` is the league's `waiver_budget` cached on `seasons`; `faab_used` is the roster's
`settings.waiver_budget_used`. Record and points come from the same `settings` block, recombining
Sleeper's split integers (`fpts` plus `fpts_decimal / 100`, and the `fpts_against` pair).

Elimination is derived from two sources and only one of them is authoritative. **The Weekly
Adjudicator is authoritative**: an `elimination` row in `public.league_events`, ruled
deterministically from `public.weekly_results`, sets `is_eliminated`, `eliminated_week`, and
`elimination_source = 'adjudicator'`. Before the Adjudicator has ruled for a week, the sync may
infer elimination from Sleeper — a roster that has stopped appearing in `get_matchups` for the
current week, or a roster whose Sleeper metadata Ben has tagged — and writes it with
`elimination_source = 'sleeper_inferred'`. An inferred value never overwrites an adjudicated one,
and consumers treat `sleeper_inferred` as provisional and label it as such. `state_version`
increments only when `is_eliminated` or `eliminated_week` changes, so a consumer can correlate a
state change with the `league_events` row that caused it.

### `public.player_projections`

`season int not null`, `week int not null`, `sleeper_player_id text not null`,
`unique (season, week, sleeper_player_id)`; `stat_line jsonb not null`,
`league_points numeric(8,2)`, `pts_ppr numeric(8,2)`, `pts_half_ppr numeric(8,2)`,
`pts_std numeric(8,2)`, `scoring_version text not null`, `source text not null default 'sleeper'`,
`coverage_flagged boolean not null default false`, `run_coverage_pct numeric(5,2)`,
`projected_at timestamptz not null`, `synced_at timestamptz not null`. Indexed on
`(season, week)` and `sleeper_player_id`.

The key is the plain season year, not `season_id`: projections are a property of the NFL week, not
of the league. `stat_line` holds Sleeper's raw projection map verbatim so any scoring change can
be replayed without refetching. This table supersedes the foundation's planned
`private.projection_snapshots`, which is not created.

**Scoring computation.** `league_points` is the dot product of the stat line and the cached
scoring settings: for every key present in both maps, multiply the projected stat by its scoring
value and sum, rounded half-up to two decimals. Sleeper uses the same stat keys in projections and
in `scoring_settings` (`pass_yd`, `rec`, `rush_td`, `bonus_rec_te`, `fum_lost`, `pass_int`, …),
which is what makes the dot product exactly right, including bonuses and negatives. Non-numeric
values and Sleeper's convenience fields (`pts_ppr`, `pts_half_ppr`, `pts_std`, `gp`, `gms_active`,
and anything else on an explicit denylist) are excluded from the product and stored only in their
own columns. `league_points` is null when the stat line cannot be scored at all; a null is a
missing projection, never a zero. `scoring_version` is the first 12 hex characters of a SHA-256
over the canonicalized `seasons.scoring_settings`; when it changes, the next projections run
rescores the current week's rows from stored `stat_line` values without refetching, and past weeks
keep the version they were scored under unless `ug sleeper projections --rescore --week N` is run
deliberately. Each run compares its computed points against Sleeper's own `pts_ppr` /
`pts_half_ppr` / `pts_std`; if more than 2 percent of scored players differ from the nearest preset
by more than 3 points, the run posts one drift note to `#guillotine-ops`.

### `public.team_week_projections`

`season_id`, `team_id`, `week int not null`, `unique (season_id, team_id, week)`;
`projected_points numeric(8,2) not null`, `starter_slots int not null`, `filled_slots int not
null`, `empty_slots int not null`, `starters_projected int not null`, `missing_projections int not
null`, `coverage_pct numeric(5,2) not null`, `is_provisional boolean not null default false`,
`computed_at timestamptz not null`.

This is a written table, not a view or a materialized view, for two reasons: Supabase Realtime
publishes tables only, and the board's sort key should be a single indexed read. It is recomputed
by the projections job, in the same transaction that writes the projections it sums.

`projected_points` is the sum of `league_points` over the team's `roster_holdings` rows with
`slot = 'starter'` for that week. An **empty starter slot** contributes zero to the sum, increments
`empty_slots`, and is excluded from the coverage denominator — nobody can project a slot the
manager left blank, and the zero is the honest number. A **missing projection** on a filled slot
also contributes zero but increments `missing_projections` and lowers coverage.
`coverage_pct = starters_projected / filled_slots * 100`, and is 100 when `filled_slots` is zero.
`is_provisional` is true when `coverage_pct` is below 95, and consumers must then render
"projection unavailable" rather than the number.

### `public.nfl_state`

A single row: `id int primary key default 1 check (id = 1)`, `season int not null`,
`season_type text not null`, `week int not null`, `display_week int`, `leg int`,
`previous_season int`, `season_start_date date`, `raw jsonb not null`,
`synced_at timestamptz not null`.

## Sync Jobs

`ug sleeper sync` gains three responsibilities inside `sync_season`'s existing single transaction,
so the board never observes a half-synced league: cache `scoring_settings`, `roster_positions`,
and `waiver_budget` onto the season row from `get_league()`; write `public.roster_holdings` for
every roster; write `public.team_season_state`. `SleeperRoster` grows `starters`, `reserve`,
`taxi`, `settings`, and `metadata` fields, each with the same null-to-empty validator `players`
already has.

`ug sleeper projections [--week N] [--rescore]` is new. `SleeperClient` gains a read-only
`get_projections(season, week)`; because the projections endpoint sits outside `/v1`, it issues an
absolute `https://api.sleeper.app/projections/nfl/{season}/{week}?season_type=regular` request
through the same client, keeping the pinned timeout and `follow_redirects = False`. The job writes
`public.player_projections`, then recomputes `public.team_week_projections` for the week, then
evaluates the coverage gate.

**The coverage gate is the same 95 percent gate Game Pulse specifies**, evaluated once per run
over all filled starter slots of all non-eliminated teams. Below the gate the rows are still
written — flagged, never withheld: `coverage_flagged = true` and `run_coverage_pct` set on the
run's projection rows, `is_provisional = true` on the affected `team_week_projections` rows, and
one ops note to `#guillotine-ops`. Consumers must show "projection unavailable" instead of a
number for any provisional team. Game Pulse's existing behavior (omit percentages, post the
factual fallback) is unchanged; it now reads the gate result out of the data rather than computing
its own.

`ug sleeper state` is new and does one thing: upsert `public.nfl_state` from `get_nfl_state`.

## Realtime

The migration adds `public.roster_holdings`, `public.team_season_state`,
`public.team_week_projections`, and `public.nfl_state` to the `supabase_realtime` publication so
the web board updates without polling. `public.player_projections` is deliberately left out — a run
touches thousands of rows and would flood every open board; the board fetches a team's player
projections on expand and re-fetches when that team's row changes.

Replica identity: primary-key default is enough for the three tables that only ever see inserts
and updates. `public.roster_holdings` is set to `replica identity full`, because it is the one
table that deletes rows and the client needs the old row's `team_id` and `sleeper_player_id` to
evict it from cache. The extra WAL is negligible at roughly 18 teams times 20 players.

## Idempotency, Versioning, Retention

Every write is an upsert on a natural key: `roster_holdings` on
`(season_id, team_id, sleeper_player_id)`, `team_season_state` on `(season_id, team_id)`,
`player_projections` on `(season, week, sleeper_player_id)`, `team_week_projections` on
`(season_id, team_id, week)`, `nfl_state` on the constant `id`. `roster_holdings` additionally
deletes, in the same transaction, any row for a synced team whose player id was not in the fetched
set. Run-level idempotency is already handled by `run_scheduled`'s per-agent, per-minute key.

Versioning is deliberately minimal. Caches keyed by natural keys with a `synced_at` do not need
versions; freshness is a timestamp comparison. The two exceptions are `team_season_state.
state_version`, which tracks adjudicated elimination changes, and `player_projections.
scoring_version`, which records the scoring settings a row's points were computed under.

Retention keeps everything. Past weeks of `player_projections` (roughly 18k rows a season) and
`team_week_projections` (324 rows a season) are never pruned, so Trade Advisor and the Storyteller
can look backward. `roster_holdings` and `team_season_state` are current-state only; roster and
record history live in `league_events`, `weekly_results`, and `trades`.

## Failure Behavior

A Sleeper outage, timeout, or non-2xx aborts the job's transaction and `run_scheduled` records the
run `failed`. The last good rows survive untouched — the board keeps showing the previous
projections and rosters, and `synced_at` simply stops advancing, which is how everything downstream
learns the data is stale. Exactly one ops note is posted, on the transition from succeeded to
failed, and one more on recovery; consecutive failures inside a 60-minute suppression window are
silent, because the 5-minute `guillotine-health` job already reports sustained staleness. A partial
roster response is rejected the same way `sync_season` already rejects one, by comparing against
`seasons.expected_rosters`; a thin or empty projections payload is refused outright, mirroring the
`sync_players` guard, so a 200 with no body can never zero out a week. Consumers surface the age:
the board shows "data as of <time>" from `max(synced_at)` with a stale badge past 30 minutes, and
bot answers append the same timestamp.

## Trade Registrar Change

Once `public.roster_holdings` exists, `build_roster_index` in
`packages/league-automation/src/ultimate_guillotine/trades/resolve.py` reads from it instead of
calling `client.get_rosters`, joining `roster_holdings` to `teams` to `seasons` on the season year
and grouping to the same `RosterIndex.holdings` shape, so `RosterIndex`, `holds()`, and the
registrar's tests are unchanged. This makes trade resolution survive a Sleeper outage — a 🚨 alert
arriving mid-outage still resolves against the last good rows — and removes a Sleeper call from
every alert. The `client` parameter stays for one guard: if the season has no `roster_holdings`
rows, or `max(synced_at)` is older than 6 hours, the function falls back to `client.get_rosters`
once, so the registrar is never blocked by a stalled sync.

## Consumers

- **League board (`apps/web`)**: `teams` and `members` for the 18 rows, `team_week_projections`
  for the sort key and displayed projection (`is_provisional` renders "projection unavailable"),
  `team_season_state` for FAAB remaining, record, and elimination, `roster_holdings` joined to
  `players` and `player_projections` for the expandable roster, `nfl_state` for the week. Realtime
  on all four published tables. This retires the direct-from-browser `useLeagueRosters`,
  `useLeagueUsers`, and `useLeagueGulagData` hooks and the legacy FantasyData `fpts_ppr` shape.
- **Trade Advisor**: `roster_holdings` plus `players` for holdings and positional surplus,
  `player_projections` for value over the next weeks, `team_season_state` for FAAB capacity and
  guillotine pressure, `trades` and `trade_revisions` for history, `nfl_state` for the horizon.
- **League Concierge data questions**: `team_week_projections` for comparisons and "bottom 5 right
  now", `team_season_state`, `roster_holdings`, `nfl_state`; every answer cites `synced_at`.
- **Game Pulse**: `player_projections` as the Monte Carlo input, `roster_holdings` filtered to
  `slot = 'starter'` for remaining starters, `team_week_projections.coverage_pct` for its 95
  percent gate, `nfl_state` for the week.
- **Weekly Adjudicator**: unchanged owner of `weekly_results` and elimination `league_events`;
  reads `team_season_state` only to detect drift and writes the authoritative elimination back.
- **Trade Registrar**: `build_roster_index`, as above.

## Privacy and Safety

Everything in this layer is public Sleeper data that any league member can already see in the app.
No contact details, no chat content, no message GUIDs. All five tables are anon-readable by design
because the board is public, and all 18 teams are treated identically — there is no per-member
visibility rule anywhere in this layer.

## Test and Rollout

Tests cover slot classification across `starters` / `reserve` / `taxi` / `players`, a `"0"` empty
starter slot, a dropped player disappearing from `roster_holdings`, FAAB recombination, the
elimination precedence rule (inferred never overwrites adjudicated), the scoring dot product
against a hand-computed stat line, a missing projection staying null rather than zero, coverage
above and below 95 percent, an empty projections payload being refused, a Sleeper outage leaving
prior rows intact, and repeated runs producing byte-identical rows. Rollout order: ship the
migration, extend `ug sleeper sync` and watch two sync cycles in `#guillotine-ops`, then add the
projections job and confirm coverage passes for a full week before the board reads it.

## Out of Scope

- Weekly roster snapshots, projection history beyond the latest value per week, and any non-Sleeper
  projection provider.
- Actual scoring, elimination rulings, and survival odds, which stay with Weekly Adjudicator and
  Game Pulse.
- Any write path from the web app; `anon` stays read-only everywhere.

## Open Questions for Ben

1. Does an eliminated roster stay in Sleeper with its players, or do you remove it? The interim
   `sleeper_inferred` elimination rule depends on which, and I would rather match what you actually
   do than guess.
2. Is `*/30` off-hours and `*/5` during Thursday/Sunday/Monday game windows the right projections
   cadence, or do you want it tighter on Sunday afternoons?
3. Do you want weekly roster snapshots kept (a `roster_holdings_history` table), so Trade Advisor
   can say what a team looked like when a trade was made? It is cheap now and expensive to
   reconstruct later.
4. FAAB budget: should `waiver_budget` come only from Sleeper, or does the league ever run a
   different budget than what Sleeper is configured with?
5. Should the board show a provisional projection with a warning badge instead of hiding the number
   entirely when coverage is below 95 percent?

## Decisions from Ben (2026-09-09)

- Final rosters of eliminated teams must be frozen: when a team's elimination is recorded, its holdings at that moment are snapshotted (a `public.final_rosters` table keyed by season and team, or an `as_of_week`/`frozen_at` marker on `roster_holdings` — the plan chooses) and later Sleeper roster changes for that team never overwrite the snapshot. Consumers show the frozen roster for eliminated teams.
- `public.members` gains public `sleeper_display_name` (written by `ug sleeper sync` from Sleeper's user record) and `nickname` (written by `ug members aliases load` as the first alias, null when none). The board and the Concierge label owners by nickname, falling back to the Sleeper display name; the bare username is never shown.
