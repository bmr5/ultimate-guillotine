-- Private collection, persisted retries, and explicit commissioner rulings.
set local lock_timeout = '10s';
create table private.archive_seasons (
  season_id bigint primary key references public.seasons(id),
  enabled boolean not null default false,
  scope text not null check (scope in ('production', 'test')),
  rules_version text not null check (rules_version = 'gulag-2026-v1'),
  started_at timestamptz not null,
  schedule jsonb not null,
  last_capture_at timestamptz
);
create table private.team_state_observations (
  id bigint generated always as identity primary key,
  season_id bigint not null references public.seasons(id),
  scope text not null check (scope in ('production', 'test')),
  week int not null check (week between 1 and 17),
  observed_at timestamptz not null,
  content_hash text not null,
  payload jsonb not null
);
create index archive_observations_lookup on private.team_state_observations
  (season_id, scope, week, observed_at desc);
create table private.archive_week_jobs (
  season_id bigint not null references public.seasons(id),
  scope text not null check (scope in ('production', 'test')),
  week int not null check (week between 1 and 17),
  status text not null default 'pending' check (status in ('pending', 'unresolved', 'confirmed')),
  cutoff_observation_id bigint references private.team_state_observations(id),
  first_complete_at timestamptz,
  candidate_hash text,
  stable_since timestamptz,
  published_hash text,
  next_check_at timestamptz not null,
  last_error text,
  primary key (season_id, scope, week)
);
create table private.archive_rulings (
  id bigint generated always as identity primary key,
  season_id bigint not null references public.seasons(id),
  scope text not null check (scope in ('production', 'test')),
  week int not null check (week between 1 and 17),
  actor text not null,
  reason text not null,
  recorded_at timestamptz not null default now(),
  payload jsonb not null
);
create index archive_rulings_lookup on private.archive_rulings(season_id, scope, week, id desc);

alter table public.season_history_weeks add column input_hash text;
create unique index archive_publish_idempotency on public.season_history_weeks
  (season_id, scope, week, revision, input_hash);
alter table public.team_event_snapshots
  add column source_observation_id bigint references private.team_state_observations(id),
  add column cutoff_precision text not null default 'observed' check (cutoff_precision in ('observed', 'unknown'));

revoke all on private.archive_seasons, private.team_state_observations,
  private.archive_week_jobs, private.archive_rulings from public, anon, authenticated;
revoke all on private.team_state_observations, private.archive_rulings from automation_worker;
grant select, insert on private.team_state_observations, private.archive_rulings to automation_worker;
grant select, insert, update on private.archive_seasons, private.archive_week_jobs to automation_worker;
grant usage, select on sequence private.team_state_observations_id_seq, private.archive_rulings_id_seq to automation_worker;

-- Replace the old first-observed freeze as the board's archive source once this season is
-- enabled. Old-season freezes remain readable. An unresolved/retracted ruling has no final
-- roster. Ordinary roster sync may keep its legacy cache, but cannot override this view.
create view public.effective_final_rosters with (security_invoker = true) as
select s.season_id, s.team_id, w.week as eliminated_week,
  coalesce((select jsonb_agg(jsonb_build_object('sleeper_player_id', p.player_id,
      'slot', p.slot, 'slot_index', null, 'lineup_position', p.position) order by p.player_id)
    from public.team_event_players p where p.snapshot_id = s.id and p.owned_at_cutoff), '[]'::jsonb) as holdings,
  s.effective_at as frozen_at
from public.team_event_snapshots s
join public.season_history_current_weeks w on w.id = s.week_revision_id
where w.status = 'confirmed' and s.event_type = 'eliminated'
union all
select f.season_id, f.team_id, f.eliminated_week, f.holdings, f.frozen_at
from public.final_rosters f
where not exists (
  select 1 from public.season_history_weeks w where w.season_id = f.season_id and w.scope = 'production'
);
grant select on public.effective_final_rosters to anon, authenticated, automation_worker;

alter table public.season_history_weeks add column is_correction boolean not null default false;
create or replace view public.season_history_current_weeks with (security_invoker = true) as
  select distinct on (season_id, week)
    id, season, week, revision, status, remaining_teams, checked_at, rules_version, is_correction
  from public.season_history_weeks
  where scope = 'production'
  order by season_id, week, revision desc;
