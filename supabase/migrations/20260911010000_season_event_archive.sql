-- Read model for History > 2026 season. The capture/adjudication job is a separate rollout.
-- A publisher inserts a whole week revision, its event snapshots, and player rows in ONE
-- transaction. Corrections replace the whole week's bundle; old revisions stay immutable.
-- No source payloads, chat messages, or private money obligations belong in these tables.

create table public.season_history_weeks (
  id bigint generated always as identity primary key,
  season_id bigint not null references public.seasons (id),
  season int not null references public.seasons (year) check (season >= 2026),
  week int not null check (week between 1 and 17),
  revision int not null check (revision > 0),
  scope text not null check (scope in ('production', 'test')),
  status text not null check (status in ('provisional', 'confirmed', 'unresolved', 'retracted')),
  remaining_teams int check (remaining_teams between 1 and 18),
  checked_at timestamptz not null,
  rules_version text not null,
  unique (season_id, scope, week, revision),
  unique (id, season_id)
);

-- A composite key prevents a publisher mixing a season year with another season's id.
alter table public.seasons add constraint seasons_id_year_archive_key unique (id, year);
alter table public.season_history_weeks add constraint history_week_season_identity
  foreign key (season_id, season) references public.seasons (id, year);
alter table public.teams add constraint teams_id_season_archive_key unique (id, season_id);

create table public.team_event_snapshots (
  id bigint generated always as identity primary key,
  week_revision_id bigint not null,
  season_id bigint not null,
  event_key text not null,
  event_type text not null check (event_type in
    ('gulag_qualified', 'gulag_entered', 'gulag_survived', 'eliminated', 'champion')),
  team_id bigint not null,
  team_label text not null check (length(team_label) between 1 and 120),
  manager_label text check (length(manager_label) <= 120),
  qualification_week int check (qualification_week between 1 and 11),
  contest_week int check (contest_week between 2 and 12),
  contest_id text,
  qualifier_team_id bigint,
  qualifier_label text check (length(qualifier_label) <= 120),
  beneficiary_team_id bigint,
  beneficiary_label text check (length(beneficiary_label) <= 120),
  accepted_substitution_event_id bigint references public.league_events (id),
  elimination_reason text check (elimination_reason in ('gulag_loss', 'direct_cut', 'championship_loss')),
  score numeric(10, 2),
  opponent_label text check (length(opponent_label) <= 120),
  opponent_score numeric(10, 2),
  faab_remaining numeric(12, 2),
  money_as_of timestamptz,
  effective_at timestamptz,
  roster_coverage text not null check (roster_coverage in ('complete', 'partial', 'missing')),
  money_coverage text not null check (money_coverage in ('complete', 'partial', 'missing')),
  foreign key (week_revision_id, season_id) references public.season_history_weeks (id, season_id),
  foreign key (team_id, season_id) references public.teams (id, season_id),
  foreign key (qualifier_team_id, season_id) references public.teams (id, season_id),
  foreign key (beneficiary_team_id, season_id) references public.teams (id, season_id),
  unique (week_revision_id, event_key),
  unique (week_revision_id, event_type, team_id),
  check ((event_type = 'eliminated') = (elimination_reason is not null)),
  check (contest_week is null or qualification_week is null or contest_week = qualification_week + 1),
  check (money_coverage <> 'complete' or (faab_remaining is not null and money_as_of is not null)),
  check (money_coverage <> 'missing' or faab_remaining is null)
);

create table public.team_event_players (
  snapshot_id bigint not null references public.team_event_snapshots (id),
  player_id text not null,
  player_label text not null check (length(player_label) between 1 and 120),
  position text,
  slot text check (slot in ('starter', 'bench', 'ir', 'taxi')),
  started boolean not null,
  owned_at_cutoff boolean not null,
  keeper boolean,
  points numeric(10, 2),
  primary key (snapshot_id, player_id)
);

alter table public.season_history_weeks enable row level security;
alter table public.team_event_snapshots enable row level security;
alter table public.team_event_players enable row level security;

revoke all on public.season_history_weeks, public.team_event_snapshots, public.team_event_players from anon, authenticated;
grant select on public.season_history_weeks, public.team_event_snapshots, public.team_event_players to anon, authenticated;

create policy "Public production history weeks" on public.season_history_weeks
  for select to anon, authenticated using (scope = 'production');
create policy "Public production event snapshots" on public.team_event_snapshots
  for select to anon, authenticated using (exists (
    select 1 from public.season_history_weeks w where w.id = week_revision_id and w.scope = 'production'
  ));
create policy "Public production event players" on public.team_event_players
  for select to anon, authenticated using (exists (
    select 1 from public.team_event_snapshots s where s.id = snapshot_id
  ));

-- Append-only for the worker. A revision, including retraction, never edits an old snapshot.
grant select, insert on public.season_history_weeks, public.team_event_snapshots, public.team_event_players to automation_worker;
grant usage, select on sequence public.season_history_weeks_id_seq, public.team_event_snapshots_id_seq to automation_worker;
create policy "Worker reads history weeks" on public.season_history_weeks for select to automation_worker using (true);
create policy "Worker appends history weeks" on public.season_history_weeks for insert to automation_worker with check (true);
create policy "Worker reads event snapshots" on public.team_event_snapshots for select to automation_worker using (true);
create policy "Worker appends event snapshots" on public.team_event_snapshots for insert to automation_worker with check (true);
create policy "Worker reads event players" on public.team_event_players for select to automation_worker using (true);
create policy "Worker appends event players" on public.team_event_players for insert to automation_worker with check (true);

-- Pick the latest revision BEFORE inspecting status, so a retraction cannot resurrect the
-- preceding confirmed week. These invoker views obey the caller's table RLS policies.
create view public.season_history_current_weeks with (security_invoker = true) as
  select distinct on (season_id, week)
    id, season, week, revision, status, remaining_teams, checked_at, rules_version
  from public.season_history_weeks
  where scope = 'production'
  order by season_id, week, revision desc;

create view public.season_history_current_events with (security_invoker = true) as
  select s.id, s.week_revision_id, s.event_key, s.event_type, s.team_id, s.team_label,
    s.manager_label, s.qualification_week, s.contest_week, s.contest_id, s.qualifier_label,
    s.beneficiary_label, s.elimination_reason, s.score, s.opponent_label, s.opponent_score,
    s.faab_remaining, s.money_as_of, s.effective_at, s.roster_coverage, s.money_coverage
  from public.team_event_snapshots s
  join public.season_history_current_weeks w on w.id = s.week_revision_id
  where w.status <> 'retracted';

create view public.season_history_current_players with (security_invoker = true) as
  select p.* from public.team_event_players p
  join public.season_history_current_events e on e.id = p.snapshot_id;

grant select on public.season_history_current_weeks, public.season_history_current_events,
  public.season_history_current_players to anon, authenticated, automation_worker;
