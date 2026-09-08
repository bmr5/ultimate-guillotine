-- Public league schema: seasons, members, teams, weekly_results, league_events,
-- trades, trade_revisions, survival_snapshots, recaps.
-- Every table gets an identity primary key, a created_at timestamp, RLS enabled,
-- select-only grants to anon/authenticated, and a "Public <table> are readable" policy.

create table public.seasons (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  year int not null unique,
  sleeper_league_id text not null,
  phase text not null default 'preseason',
  rules_version text not null,
  expected_rosters int not null default 18
);

create table public.members (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  display_name text not null unique
);

create table public.teams (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  member_id bigint not null references public.members (id),
  sleeper_user_id text not null,
  sleeper_roster_id int not null,
  team_name text not null,
  unique (season_id, sleeper_roster_id),
  unique (season_id, member_id)
);

create index teams_season_id_idx on public.teams (season_id);
create index teams_member_id_idx on public.teams (member_id);

create table public.weekly_results (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  week int not null,
  team_id bigint not null references public.teams (id),
  points numeric(8, 2) not null,
  state_version int not null default 1,
  is_final boolean not null default false,
  unique (season_id, week, team_id, state_version)
);

create index weekly_results_season_id_idx on public.weekly_results (season_id);
create index weekly_results_team_id_idx on public.weekly_results (team_id);

create table public.league_events (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  week int,
  event_type text not null,
  occurred_at timestamptz not null,
  payload jsonb not null default '{}',
  idempotency_key text unique
);

create index league_events_season_id_idx on public.league_events (season_id);

create table public.trades (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  trade_code text not null unique,
  current_revision_id bigint,
  status text not null default 'accepted' check (status in ('accepted', 'rescinded'))
);

create index trades_season_id_idx on public.trades (season_id);

create table public.trade_revisions (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  trade_id bigint not null references public.trades (id),
  revision int not null,
  terms jsonb not null,
  source_message_guid text,
  effective_week int,
  unique (trade_id, revision)
);

create index trade_revisions_trade_id_idx on public.trade_revisions (trade_id);

create table public.survival_snapshots (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  week int not null,
  game_window text not null,
  snapshot_at timestamptz not null,
  projection_source text,
  model_version text not null,
  simulations int not null,
  input_hash text not null,
  results jsonb not null,
  unique (season_id, week, game_window, input_hash, model_version)
);

create index survival_snapshots_season_id_idx on public.survival_snapshots (season_id);

create table public.recaps (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  week int not null,
  recap_kind text not null,
  state_version int not null,
  prompt_version text not null,
  facts_hash text not null,
  body text not null,
  publication_state text not null default 'draft'
    check (publication_state in ('draft', 'sent', 'corrected')),
  unique (season_id, week, recap_kind, state_version, prompt_version, facts_hash)
);

create index recaps_season_id_idx on public.recaps (season_id);

-- Row level security: read-only for anon/authenticated on all nine tables.
alter table public.seasons enable row level security;
alter table public.members enable row level security;
alter table public.teams enable row level security;
alter table public.weekly_results enable row level security;
alter table public.league_events enable row level security;
alter table public.trades enable row level security;
alter table public.trade_revisions enable row level security;
alter table public.survival_snapshots enable row level security;
alter table public.recaps enable row level security;

-- Supabase's default privileges grant all table privileges to anon/authenticated on
-- creation; revoke everything first so only select remains.
revoke all on public.seasons from anon, authenticated;
revoke all on public.members from anon, authenticated;
revoke all on public.teams from anon, authenticated;
revoke all on public.weekly_results from anon, authenticated;
revoke all on public.league_events from anon, authenticated;
revoke all on public.trades from anon, authenticated;
revoke all on public.trade_revisions from anon, authenticated;
revoke all on public.survival_snapshots from anon, authenticated;
revoke all on public.recaps from anon, authenticated;

grant select on public.seasons to anon, authenticated;
grant select on public.members to anon, authenticated;
grant select on public.teams to anon, authenticated;
grant select on public.weekly_results to anon, authenticated;
grant select on public.league_events to anon, authenticated;
grant select on public.trades to anon, authenticated;
grant select on public.trade_revisions to anon, authenticated;
grant select on public.survival_snapshots to anon, authenticated;
grant select on public.recaps to anon, authenticated;

create policy "Public seasons are readable" on public.seasons for select using (true);
create policy "Public members are readable" on public.members for select using (true);
create policy "Public teams are readable" on public.teams for select using (true);
create policy "Public weekly_results are readable" on public.weekly_results for select using (true);
create policy "Public league_events are readable" on public.league_events for select using (true);
create policy "Public trades are readable" on public.trades for select using (true);
create policy "Public trade_revisions are readable" on public.trade_revisions for select using (true);
create policy "Public survival_snapshots are readable" on public.survival_snapshots for select using (true);
create policy "Public recaps are readable" on public.recaps for select using (true);

-- Seed season 2026.
insert into public.seasons (year, sleeper_league_id, phase, rules_version, expected_rosters)
values (2026, '1389372259260452864', 'preseason', '2026.1', 18)
on conflict (year) do update set sleeper_league_id = excluded.sleeper_league_id;
