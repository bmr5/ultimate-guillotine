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
