-- The player card's data: what a player went for at the auction and everything that has
-- happened to him since. Spec: docs/superpowers/specs/2026-09-10-player-card-design.md.
--
-- Three tables in the data layer's standard shape (see 20260909151435_league_data_layer.sql):
-- identity key, created_at, RLS on, select for anon/authenticated behind a "Public <table> are
-- readable" policy, an "Automation writes <table>" policy for automation_worker with
-- select/insert/update and no delete. None is a cache — a pick, an executed transaction, and
-- a move are facts — so nothing here is ever deleted, and none of them joins the Realtime
-- publication: the mark rides on roster_holdings, which already streams, and the card fetches
-- on open.
--
-- Everything is keyed by season_id. Ben (2026-09-10): "season data and trades and draft should
-- stay within season for this feature."

-- One row per auction pick. team_id is the pick's roster_id resolved through
-- teams (season_id, sleeper_roster_id); position is what Sleeper recorded on the pick, which is
-- what the auction ranked by; drafted_at is the draft's start_time, the same on every row, so
-- the journey's first entry has a date. No foreign key to public.players, for the reason
-- roster_holdings has none: the directory keeps skill positions only.
create table public.draft_picks (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  team_id bigint not null references public.teams (id),
  sleeper_player_id text not null,
  sleeper_draft_id text not null,
  pick_no int not null,
  round int not null,
  draft_slot int not null,
  position text,
  -- An auction league: a pick without a price is a malformed payload, not a free player.
  amount int not null check (amount >= 1),
  drafted_at timestamptz not null,
  synced_at timestamptz not null,
  unique (season_id, sleeper_player_id),
  unique (season_id, sleeper_draft_id, pick_no)
);
create index draft_picks_team_idx on public.draft_picks (team_id);

-- One row per completed Sleeper transaction. week is Sleeper's own `leg`, never the clock;
-- occurred_at is status_updated, else created; team_ids are roster_ids resolved to teams;
-- faab_moves entries are {"amount", "from_team_id", "to_team_id"}; waiver_bid is
-- settings.waiver_bid on a claim and null otherwise; raw is the record verbatim so a later
-- reparse never needs a refetch, on the same reasoning as player_projections.stat_line.
-- Failed waiver bids are not stored: 2025 had 1,269 of them, and they say nothing about a
-- player's journey.
create table public.transactions (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  sleeper_transaction_id text not null unique,
  kind text not null check (kind in ('trade', 'waiver', 'free_agent', 'commissioner')),
  week int not null,
  occurred_at timestamptz not null,
  team_ids bigint[] not null default '{}',
  faab_moves jsonb not null default '[]',
  waiver_bid int,
  raw jsonb not null,
  synced_at timestamptz not null
);
create index transactions_season_week_idx on public.transactions (season_id, week);
create index transactions_season_occurred_idx on public.transactions (season_id, occurred_at);

-- One row per player per side of a transaction: every entry in `adds` is an add for its
-- roster's team and every entry in `drops` a drop for its. A trade yields an add for the
-- receiver and a drop for the sender per player. This is the per-player index the card reads;
-- transactions alone would need a JSON scan.
create table public.transaction_moves (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  transaction_id bigint not null references public.transactions (id),
  season_id bigint not null references public.seasons (id),
  sleeper_player_id text not null,
  team_id bigint not null references public.teams (id),
  action text not null check (action in ('add', 'drop')),
  unique (transaction_id, sleeper_player_id, action)
);
create index transaction_moves_season_player_idx
  on public.transaction_moves (season_id, sleeper_player_id);

alter table public.draft_picks enable row level security;
alter table public.transactions enable row level security;
alter table public.transaction_moves enable row level security;

revoke all on public.draft_picks from anon, authenticated;
revoke all on public.transactions from anon, authenticated;
revoke all on public.transaction_moves from anon, authenticated;
grant select on public.draft_picks to anon, authenticated;
grant select on public.transactions to anon, authenticated;
grant select on public.transaction_moves to anon, authenticated;

create policy "Public draft_picks are readable" on public.draft_picks
  for select using (true);
create policy "Automation writes draft_picks" on public.draft_picks
  for all to automation_worker using (true) with check (true);
create policy "Public transactions are readable" on public.transactions
  for select using (true);
create policy "Automation writes transactions" on public.transactions
  for all to automation_worker using (true) with check (true);
create policy "Public transaction_moves are readable" on public.transaction_moves
  for select using (true);
create policy "Automation writes transaction_moves" on public.transaction_moves
  for all to automation_worker using (true) with check (true);

-- No delete grant on any of the three; roster_holdings stays the one public table the worker
-- may delete from.
grant select, insert, update on public.draft_picks to automation_worker;
grant select, insert, update on public.transactions to automation_worker;
grant select, insert, update on public.transaction_moves to automation_worker;
grant usage, select on all sequences in schema public to automation_worker;
