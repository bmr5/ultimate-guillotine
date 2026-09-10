# Player Card and the Drafted-Here Mark

## Purpose

Two things every league member wants to know about a player on the board and cannot see without
opening Sleeper: what he went for at the auction and to whom, and everything that has happened to
him since. This feature adds a small mark beside a player's name when he is still on the team that
drafted him, and a tappable card for any player showing his draft price and drafter, where that
price sat in the auction, his numbers, and his season journey — drafted, traded, dropped, claimed —
with the league's own trade announcements attached where they match.

This spec uses the shared design in `docs/superpowers/specs/2026-08-27-automation-foundation-design.md`
and reads the board through `docs/superpowers/specs/2026-09-09-league-data-layer-design.md` and
`docs/superpowers/specs/2026-09-09-league-board-design.md`. It adds tables to the data layer and a
view to the board; it defines no agent, no message, and no language-model call.

**Everything is scoped to one season.** Ben (2026-09-10): "I don't want to complicate trying to
separate out the years right now. just build into the design that season data and trades and
draft should stay within season for this feature." Every table below is keyed by `season_id`, every
query filters to the board's active season, and the card never mixes seasons. Sleeper holds the
full 2025 auction and 2025 transaction log through the league's `previous_league_id` chain; loading
them is a follow-up that adds a league id, not a schema.

## What Sleeper Holds

Checked live on 2026-09-10 against league `1389372259260452864`:

- `GET /v1/league/{league_id}` carries `draft_id`, the league's canonical draft. Listing
  `/league/{league_id}/drafts` is the wrong key: the 2025 league also carries an abandoned
  one-pick draft.
- `GET /v1/draft/{draft_id}` carries `type` (`auction`), `status` (`complete`), `start_time` (ms),
  and `settings.teams`, `settings.rounds`, `settings.budget`.
- `GET /v1/draft/{draft_id}/picks` returns one record per pick: `pick_no`, `round`, `draft_slot`,
  `roster_id`, `picked_by` (user id), `player_id`, and `metadata.amount` as a string. 2026 has 162
  picks (18 teams × 9 rounds), every one with an amount and a picker, and `picked_by` equals the
  roster's owner on all 162. Total spent: $2,293 of $3,600.
- `GET /v1/league/{league_id}/transactions/{week}` returns the executed log for that leg: `type`
  in `trade`, `waiver`, `free_agent`, `commissioner`; `status`; `created` and `status_updated`
  (ms); `leg` (the week); `roster_ids`; `adds` and `drops` as `{player_id: roster_id}` maps
  (`adds` is the receiving roster, `drops` the sending one), `waiver_budget` as a list of
  `{amount, sender, receiver}` roster-id transfers, `settings.waiver_bid` on waiver claims, and
  `draft_picks` (always empty in this league). Failed waiver bids are in the log too — 1,269 of
  them in 2025 against 486 that completed.
- The league runs nine roster slots (`QB RB RB WR WR TE FLEX K DEF`), no bench, no IR, no taxi.
  Every rostered player is a starter, so `public.team_week_scores.players_points` already holds
  every rostered player's points for every week.

## Tables

All in the `public` schema, all in the existing shape: identity primary key, `created_at
timestamptz not null default now()`, RLS enabled, `revoke all` then `grant select` to `anon,
authenticated` behind a `"Public <table> are readable"` policy, and an `"Automation writes
<table>"` policy `for all to automation_worker using (true) with check (true)` with `select,
insert, update` grants. No `delete` grant on any of the three: nothing here is a cache. One
migration, `supabase/migrations/<timestamp>_player_card.sql`. None of the three joins the
`supabase_realtime` publication — the mark depends on `roster_holdings`, which already streams, and
the card fetches on open.

### `public.draft_picks`

`season_id bigint not null references public.seasons (id)`, `team_id bigint not null references
public.teams (id)`, `sleeper_player_id text not null`, `sleeper_draft_id text not null`,
`pick_no int not null`, `round int not null`, `draft_slot int not null`, `position text`,
`amount int not null check (amount >= 1)`, `drafted_at timestamptz not null`, `synced_at
timestamptz not null`; `unique (season_id, sleeper_player_id)`, `unique (season_id,
sleeper_draft_id, pick_no)`, index on `team_id`.

`team_id` is the pick's `roster_id` resolved through `teams (season_id, sleeper_roster_id)`.
`position` is the position Sleeper recorded on the pick, which is what the auction ranked by.
`drafted_at` is the draft's `start_time`, the same value on every row, so the journey's first
entry has a date. There is deliberately no foreign key to `public.players`, for the reason
`roster_holdings` has none.

### `public.transactions`

`season_id bigint not null references public.seasons (id)`, `sleeper_transaction_id text not null
unique`, `kind text not null check (kind in ('trade', 'waiver', 'free_agent', 'commissioner'))`,
`week int not null`, `occurred_at timestamptz not null`, `team_ids bigint[] not null default
'{}'`, `faab_moves jsonb not null default '[]'`, `waiver_bid int`, `raw jsonb not null`,
`synced_at timestamptz not null`; indexes on `(season_id, week)` and `(season_id, occurred_at)`.

Only `status = 'complete'` records are stored. `week` is Sleeper's `leg`, never derived from the
clock. `occurred_at` is `status_updated` when present, else `created`. `team_ids` are the
transaction's `roster_ids` resolved to teams. `faab_moves` entries are `{"amount": int,
"from_team_id": bigint, "to_team_id": bigint}`, resolved the same way. `waiver_bid` is
`settings.waiver_bid` on a waiver claim and null otherwise. `raw` is the Sleeper record verbatim,
so a later reparse never needs a refetch, on the same reasoning as `player_projections.stat_line`.

### `public.transaction_moves`

`transaction_id bigint not null references public.transactions (id)`, `season_id bigint not null
references public.seasons (id)`, `sleeper_player_id text not null`, `team_id bigint not null
references public.teams (id)`, `action text not null check (action in ('add', 'drop'))`;
`unique (transaction_id, sleeper_player_id, action)`, index on `(season_id, sleeper_player_id)`.

One row per player per side of a transaction: every entry in `adds` is an `add` for its roster's
team and every entry in `drops` is a `drop` for its roster's team. A trade therefore yields an
add for the receiver and a drop for the sender per player; a claim yields an add and, when a
player was cut to make room, a drop. This is the per-player index the card reads; `transactions`
alone would need a JSON scan.

## Sync Jobs

Two new script-only jobs in `hermes/guillotine/cron.yaml`, each an `ug` CLI wrapped in
`run_scheduled` so it records one `private.agent_runs` row and dedupes a second fire inside the
same UTC minute. Neither folds into the ten-minute roster sync, matching how projections, scores,
and state got their own jobs. Both read through the existing read-only `SleeperClient`, which
gains `get_draft(draft_id)`, `get_draft_picks(draft_id)`, and `get_transactions(league_id,
week)`; `SleeperLeague` gains `draft_id`.

### `ug sleeper draft` — `guillotine-sleeper-draft`, agent `draft-sync`, daily at `0 6 * * *`

Fetches the league, then the draft named by `league.draft_id`, then its picks, all before opening
a transaction. If the draft's `status` is not `complete` the run is a no-op that reports
`skipped` — before the auction the job has nothing to write. Otherwise the payload must pass
three guards or the run fails with the last good rows untouched: it is non-empty; it holds at
least `settings.teams × settings.rounds` picks; and every pick carries a `metadata.amount` that
parses to an integer of at least 1 — this is an auction league and a pick without a price is a
malformed payload, not a free player. A `roster_id` with no `teams` row for the season fails the
run too: the draft is a fixed fact about eighteen rosters, and a missing one means the roster
sync has not run yet. Rows upsert on `(season_id, sleeper_player_id)` in one transaction. One
Sleeper call for the picks, 162 rows, byte-identical on a rerun. Ben runs it once by hand for
2026 as part of rollout; the daily fire exists so a corrected pick on Sleeper's side reaches the
board without anyone remembering.

### `ug sleeper transactions [--week N] [--all]` — `guillotine-sleeper-transactions`, agent `transactions-sync`, `every 10m`

Reads the current week from `public.nfl_state` under the data layer's rule (refresh inline when
the row is missing or older than 60 minutes). By default it fetches the current week and the
previous one, clamped to week 1, so a deal processed late at a week boundary is never missed; `--week N` fetches one
week; `--all` walks every week from 1 to the current one for backfill. Each week's records are
filtered to `status = 'complete'` and a known `type`; an unknown type is counted into the run's
report and skipped, on the players sync's reasoning that one new string must not stall the log.
A `roster_id` that resolves to no team is likewise counted and the record skipped, never a
failed run. Rows upsert on `sleeper_transaction_id` and moves on `(transaction_id,
sleeper_player_id, action)`; nothing is deleted. Reruns are byte-identical.

Failure behavior is the data layer's: a Sleeper outage, timeout, or non-2xx aborts the job's
transaction, `run_scheduled` records the run `failed`, the last good rows survive, and exactly one
ops note is posted on the transition from succeeded to failed and one on recovery.

## The Mark

Every board player row carries the mark when the player's `draft_picks` row belongs to the team
whose row it is — a one-line rule computed in the board's existing join, where `RosterPlayer`
gains `draft` (`{teamId, amount, pickNo, position}` or null for an undrafted pickup) and
`draftedHere`. Frozen rosters of eliminated teams use the same rule. `draft_picks` for the season
loads with the board's other queries: 162 rows, once, cached until the season changes.

The mark is rendered by the existing explained-badge component so it obeys the board's rule that
every badge explains itself on tap as well as hover, with the always-mounted screen-reader text:
a muted 12px lucide `Anchor` after the name, whose description reads "Drafted by <owner> for $53",
`<owner>` being the label the board already uses for the team — nickname, falling back to the
Sleeper display name, never the bare username. The icon is a one-line swap.

The row is drawn in two places today, and both get the mark: `PlayerRow` in the team card's
roster panel, and the inline list in the position view. Two structural fixes ship with it. The
position view's player list sits inside the card's toggle `<button>`, so a clickable name there is
a control nested in a control, which the explained-badge already documents as illegal; the list
moves out to be the toggle's sibling, as the chip row did. And the two hand-copied rows collapse
into one shared name component — name button, injury tag, mark — used by both views, with the
position view's player type widened to carry the draft fields.

## The Card

Tapping a name opens a dialog built on the same dialog primitive as the trade modal, controlled
rather than uncontrolled: the open player's Sleeper id lives in the URL as `?player=<id>` beside
the board's `sort` and `pos` params, so a card is shareable and the browser's back button closes
one opened by a tap. One dialog mounts at the page level and reads the param; rows carry no dialog
of their own. Opening pushes a history entry; closing pushes the URL without the param. A shared
link to a player no one currently rosters still opens: the header comes from `public.players` by
id, the numbers keep season points and mark this week as not rostered, and the journey ends
with the drop.

On open the card fetches three things, each a TanStack query cached like the board's others:

- the player's `transaction_moves` for the season with their `transactions` embedded;
- the season's `team_week_scores` rows selecting `week, team_id, players_points`;
- the registered trades the trades page already loads through its catalog hook, filtered to this
  player's Sleeper id in `assets` and to the board's season.

Draft pick, this week's projection, live points, position, NFL team, and injury tag are already
on the board. Sections, top to bottom, in one scrolling body:

**Header.** Full name, then `position · NFL team` and the injury tag. No bio line — Ben
(2026-09-10): "I just don't really care about the bio line honestly."

**Numbers.** This week's projection and live points in the `figures` voice, and season points to
date captioned "in N rostered weeks": the sum over every week's `team_week_scores` row whose
`players_points` names the player, N being the count of such weeks. With no bench, that is every
week the player was on any roster. No stats sync ships now; a true total including unrostered
weeks is a follow-up.

**Draft.** Price, pick number, and drafter, then the context line derived from the season's 162
picks: "9th priciest pick · 4th RB · RB average $22". Ranks are competition ranks — tied prices
share the higher rank and the next rank is skipped — and the average is rounded to the dollar.
An undrafted player reads "Undrafted" and has no context line.

**Journey.** An ordered list, oldest first, one entry per event, dated in the trade page's voice
(`Sep 9 · Wk 1`; the draft entry uses `drafted_at`):

- *Drafted* by <owner> for $53.
- *Traded* from <owner> to <owner>, naming the other players in the deal with their directions
  and every FAAB move.
- *Dropped* by <owner>. *Claimed* by <owner> for a $12 bid. *Added* by <owner> (free agent).
  *Commissioner move* to <owner>.
- *Announced* — a registered trade involving this player with no Sleeper counterpart, dated by
  its announcement.

A trade entry that matches a registered trade carries the trade code chip and the announcement
`<blockquote>` clamped to four lines, exactly as the trade cards render them; a rescinded one
renders struck through. The match is a pure function over the board's season: a Sleeper trade and
a registered trade match when the set of member ids behind the Sleeper trade's `team_ids` equals
the registered trade's party member ids and the announcement time is within 72 hours of
`occurred_at`; when several qualify the nearest in time wins, each registered trade links to at most one
Sleeper trade, and a registered trade with a party the directory cannot name never matches. A Sleeper trade with no match shows without a quote. Not every deal
executes as a Sleeper trade — a rental settled by drops, or a deal the Registrar logged that no one
processed — so the unmatched registered trades remain as *Announced* entries rather than
disappearing.

Owner labels everywhere on the card are the board's: nickname, else Sleeper display name; a party
the directory cannot name reads "a former manager", as on the trade cards.

Loading shows skeleton lines in each section. A failed fetch shows an alert inside the card naming
the section, with a retry, and never touches the board behind it. Motion follows the dialog
primitive's reduced-motion handling. The name button announces that it opens a dialog; the dialog
is labelled by the player's name; the journey is a real list.

## Privacy and Safety

Everything on the mark and the card is public Sleeper data — draft results, the executed
transaction log, rosters, projections, scores, the player directory — plus the registered-trade
fields the public trades page already renders: trade code, status, owner labels, and the
announcement text Ben chose to publish there. No private schema table is read, no member alias
table, no message content beyond that announcement, no dues, no contact details. The anon key
stays the only credential in the bundle, and every new table is anon-readable under the same
"Public … are readable" policy as the rest of the layer.

## Test and Rollout

**Mac mini side**, pytest in the existing style. Real payloads as fixtures: the 162-pick 2026
draft, the draft record, and week 1's eight transactions, beside the existing 2026 rosters so
roster ids resolve. Pure loaders tested without a database: picks parse to rows with the amount as
an integer, the roster mapped to a team, and `drafted_at` from the draft; an empty payload, a
missing amount, a short pick count, and an unresolvable roster are each refused; a draft not yet
complete is skipped. Transactions parse to moves: a trade yields an add for the receiver and a
drop for the sender per player; a claim keeps its bid; failed bids and unknown types are skipped
and the latter counted; FAAB moves and `team_ids` map to team ids; `week` comes from `leg`;
`occurred_at` prefers `status_updated`. Client calls mocked at the URL level with `respx` as the
existing client tests do. Database tests behind `TEST_DATABASE_URL`: a rerun produces
byte-identical rows, and nothing is ever deleted. The cron manifest test pins both new entries.

**Web side**, vitest, colocated. Derivations in their own modules with tests: the drafted-here
rule including frozen rosters and undrafted players; auction rank and position average with
ties; the journey builder covering ordering, every entry kind, the trade match rule with its
72-hour window and one-link-per-trade guarantee, unmatched *Announced* entries, and the season
filter; the rostered-weeks points sum. Components: the shared name renders the mark only when
drafted here, with the tooltip and screen-reader sentence; the position view no longer nests a
control inside its toggle; the card opens from the URL param on load, closes by updating the
URL, and renders its loading, error, undrafted, and not-rostered states.

**Rollout order.**

1. The migration lands; the web app's hand-written `Database` type gains the three tables.
2. Ben runs `ug sleeper draft` once on the Mac mini and checks for 162 rows in Supabase; the daily
   cron entry is added.
3. `ug sleeper transactions --all` backfills the season; the ten-minute entry is added and watched
   for two cycles in `#guillotine-ops`.
4. The mark and the card merge to main and are reviewed on the Vercel preview at 375px: a kept
   player shows the mark, the two players swapped between Rick Vice and Supreme Projections in
   week 1 do not, and a shared card URL opens on load.

**Done means** the board shows the mark from Supabase alone; any name opens a card with header,
numbers, draft, and journey; a Sleeper outage leaves the last good rows and the card still opens;
and `pnpm lint`, `pnpm test:web`, `pnpm test:agents`, and `pnpm lint:agents` all pass.

## Out of Scope

Each is a clean follow-up because every table is season-keyed:

- The 2025 season, reachable through `previous_league_id` (its auction and 144 completed trades are
  on Sleeper today).
- A true season total including unrostered weeks, via Sleeper's per-player stats endpoint.
- Clickable player names inside the trade modal.
- Realtime on the three new tables.
- The League Agent answering "who drafted X and for how much" — it can, from these rows, once it
  exists.
- Player bio (age, college, experience, number).

## Decisions from Ben (2026-09-10)

1. **This season only, season-scoped by construction.** Ben: "this is most important for 2026
   really. I don't want to complicate trying to seperate out the years right now. just build into
   the design that season data and trades and draft should stay within season for this feature."
2. **The card shows draft data, trades, the season journey, auction context, and numbers.** Bio
   was chosen, then dropped: "I just don't really care about the bio line honestly."
3. **The mark is a small glyph with a tooltip**, not the price itself on the row.
4. **Sleeper facts become data-layer rows** — chosen over draft-only and over browser-side
   Sleeper calls — so the bot, the agents, and the board read the same thing and a Sleeper outage
   degrades everything the same way.
5. **Season points derive from the weekly scores already synced**, captioned by rostered weeks;
   no stats sync now.
