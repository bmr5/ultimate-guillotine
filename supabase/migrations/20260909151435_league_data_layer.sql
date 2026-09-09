-- League data layer: roster holdings, team season state, the frozen final roster of an
-- eliminated team, player and team-week projections, and the single NFL state row, plus
-- the two owner-label columns on public.members. Same shape as the nine existing public
-- tables: identity key, created_at, RLS on, select-only for anon/authenticated, and an
-- "Automation writes <table>" policy for automation_worker.

-- The league's own settings are cached on the season row rather than in a settings
-- table: there is one row per year and every consumer already joins to it.
alter table public.seasons
  add column if not exists scoring_settings jsonb not null default '{}',
  add column if not exists roster_positions jsonb not null default '[]',
  add column if not exists waiver_budget int,
  add column if not exists league_synced_at timestamptz;

-- How an owner is labelled. members.display_name stays the natural key that sync upserts
-- on and that the alias file's sleeper_username matches; it is never rendered.
-- sleeper_display_name is refreshed from Sleeper's user record on every sync, and
-- nickname is written by `ug members aliases load` from the member's first alias.
-- Both are anon-readable because the public board renders them; every other alias stays
-- in private.member_aliases, which anon cannot reach.
alter table public.members
  add column if not exists sleeper_display_name text,
  add column if not exists nickname text;

-- Current-state cache of who holds whom. No foreign key to public.players on purpose:
-- Sleeper rosters carry ids the filtered skill-position directory drops.
create table public.roster_holdings (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  team_id bigint not null references public.teams (id),
  sleeper_player_id text not null,
  slot text not null check (slot in ('starter', 'bench', 'ir', 'taxi')),
  slot_index int,
  lineup_position text,
  synced_at timestamptz not null,
  unique (season_id, team_id, sleeper_player_id)
);
create index roster_holdings_season_player_idx
  on public.roster_holdings (season_id, sleeper_player_id);
create index roster_holdings_team_id_idx on public.roster_holdings (team_id);

create table public.team_season_state (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  team_id bigint not null references public.teams (id),
  faab_budget int not null,
  faab_used int not null,
  faab_remaining int generated always as (faab_budget - faab_used) stored,
  wins int not null default 0,
  losses int not null default 0,
  ties int not null default 0,
  points_for numeric(10, 2) not null default 0,
  points_against numeric(10, 2) not null default 0,
  is_eliminated boolean not null default false,
  eliminated_week int,
  elimination_source text
    check (elimination_source in ('adjudicator', 'sleeper_inferred', 'manual')),
  state_version int not null default 1,
  synced_at timestamptz not null,
  unique (season_id, team_id)
);
create index team_season_state_team_id_idx on public.team_season_state (team_id);

-- The roster a team was eliminated with, captured once and never rewritten.
-- roster_holdings keeps following Sleeper after a team is out, because managers go on
-- dropping and adding, so the holdings at the moment of elimination are frozen here.
-- holdings is the classify_holdings output verbatim: a JSON array of
-- {sleeper_player_id, slot, slot_index, lineup_position}, in lineup order.
-- eliminated_week is nullable because a provisional Sleeper-inferred elimination may not
-- know the week yet; the snapshot is still taken, because the roster is what changes.
create table public.final_rosters (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  team_id bigint not null references public.teams (id),
  eliminated_week int,
  holdings jsonb not null,
  frozen_at timestamptz not null,
  unique (season_id, team_id)
);
-- Keyed by the plain season year, not season_id: a projection is a property of the NFL
-- week, not of this league. stat_line keeps Sleeper's raw map so a scoring change can be
-- replayed without refetching.
create table public.player_projections (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season int not null,
  week int not null,
  sleeper_player_id text not null,
  stat_line jsonb not null,
  league_points numeric(8, 2),
  pts_ppr numeric(8, 2),
  pts_half_ppr numeric(8, 2),
  pts_std numeric(8, 2),
  scoring_version text not null,
  source text not null default 'sleeper',
  coverage_flagged boolean not null default false,
  -- The run's overall starter coverage, carried on every row it wrote. A percentage,
  -- so it is bounded here rather than trusted from the caller.
  run_coverage_pct numeric(5, 2) check (run_coverage_pct between 0 and 100),
  projected_at timestamptz not null,
  synced_at timestamptz not null,
  unique (season, week, sleeper_player_id)
);
create index player_projections_player_idx on public.player_projections (sleeper_player_id);

-- A written table, not a view: Realtime publishes tables only, and the board's sort key
-- should be one indexed read.
create table public.team_week_projections (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  team_id bigint not null references public.teams (id),
  week int not null,
  projected_points numeric(8, 2) not null,
  starter_slots int not null,
  filled_slots int not null,
  empty_slots int not null,
  starters_projected int not null,
  missing_projections int not null,
  coverage_pct numeric(5, 2) not null check (coverage_pct between 0 and 100),
  is_provisional boolean not null default false,
  computed_at timestamptz not null,
  unique (season_id, team_id, week)
);
create index team_week_projections_season_week_idx
  on public.team_week_projections (season_id, week);

create table public.nfl_state (
  id int primary key default 1 check (id = 1),
  created_at timestamptz not null default now(),
  season int not null,
  season_type text not null,
  week int not null,
  display_week int,
  leg int,
  previous_season int,
  season_start_date date,
  raw jsonb not null,
  synced_at timestamptz not null
);

alter table public.roster_holdings enable row level security;
alter table public.team_season_state enable row level security;
alter table public.final_rosters enable row level security;
alter table public.player_projections enable row level security;
alter table public.team_week_projections enable row level security;
alter table public.nfl_state enable row level security;

revoke all on public.roster_holdings from anon, authenticated;
revoke all on public.team_season_state from anon, authenticated;
revoke all on public.final_rosters from anon, authenticated;
revoke all on public.player_projections from anon, authenticated;
revoke all on public.team_week_projections from anon, authenticated;
revoke all on public.nfl_state from anon, authenticated;

grant select on public.roster_holdings to anon, authenticated;
grant select on public.team_season_state to anon, authenticated;
grant select on public.final_rosters to anon, authenticated;
grant select on public.player_projections to anon, authenticated;
grant select on public.team_week_projections to anon, authenticated;
grant select on public.nfl_state to anon, authenticated;

create policy "Public roster_holdings are readable" on public.roster_holdings
  for select using (true);
create policy "Public team_season_state are readable" on public.team_season_state
  for select using (true);
create policy "Public final_rosters are readable" on public.final_rosters
  for select using (true);
create policy "Public player_projections are readable" on public.player_projections
  for select using (true);
create policy "Public team_week_projections are readable" on public.team_week_projections
  for select using (true);
create policy "Public nfl_state are readable" on public.nfl_state for select using (true);

create policy "Automation writes roster_holdings" on public.roster_holdings
  for all to automation_worker using (true) with check (true);
create policy "Automation writes team_season_state" on public.team_season_state
  for all to automation_worker using (true) with check (true);
create policy "Automation writes final_rosters" on public.final_rosters
  for all to automation_worker using (true) with check (true);
create policy "Automation writes player_projections" on public.player_projections
  for all to automation_worker using (true) with check (true);
create policy "Automation writes team_week_projections" on public.team_week_projections
  for all to automation_worker using (true) with check (true);
create policy "Automation writes nfl_state" on public.nfl_state
  for all to automation_worker using (true) with check (true);

grant select, insert, update on public.roster_holdings to automation_worker;
grant select, insert, update on public.team_season_state to automation_worker;
-- final_rosters is the one table that gets no UPDATE grant: a snapshot is never
-- rewritten. FinalRosterRepository.freeze is insert-or-do-nothing, and the
-- unique (season_id, team_id) constraint plus the missing UPDATE grant together are
-- what make a snapshot permanent rather than merely conventional.
grant select, insert on public.final_rosters to automation_worker;
grant select, insert, update on public.player_projections to automation_worker;
grant select, insert, update on public.team_week_projections to automation_worker;
grant select, insert, update on public.nfl_state to automation_worker;
grant usage, select on all sequences in schema public to automation_worker;

-- roster_holdings is a cache, not a league fact: a dropped player must vanish. This is
-- the only public table automation_worker may delete from.
grant delete on table public.roster_holdings to automation_worker;

-- Realtime. final_rosters is published so an open board swaps an eliminated team's
-- roster the moment the freeze lands, without a refresh. player_projections is
-- deliberately excluded: a run touches thousands of rows and would flood every open
-- board. The board fetches a team's player projections on expand and re-fetches when
-- that team's row changes.
--
-- Both the publication and each membership are added conditionally: a database that
-- already carries them (a hosted project where Realtime was switched on from Studio)
-- must survive this migration unchanged.
do $$
begin
  if not exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    create publication supabase_realtime;
  end if;
end
$$;

do $$
declare
  target text;
begin
  foreach target in array array[
    'roster_holdings', 'team_season_state', 'final_rosters',
    'team_week_projections', 'nfl_state'
  ]
  loop
    if not exists (
      select 1 from pg_publication_tables
       where pubname = 'supabase_realtime'
         and schemaname = 'public'
         and tablename = target
    ) then
      execute format(
        'alter publication supabase_realtime add table public.%I', target
      );
    end if;
  end loop;
end
$$;

-- The primary-key default is enough for the four tables that only insert and update.
-- roster_holdings deletes, and the client needs the old row's team_id and
-- sleeper_player_id to evict it from cache. Roughly 18 teams times 20 players, so the
-- extra WAL is negligible.
alter table public.roster_holdings replica identity full;

-- public.player_projections supersedes the foundation's planned snapshot table, which
-- shipped empty and is referenced by no code.
drop table if exists private.projection_snapshots;
