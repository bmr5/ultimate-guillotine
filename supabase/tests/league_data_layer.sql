begin;
select plan(33);

-- `supabase db reset` seeds only public.seasons, so the row-level assertions below need
-- a member and a team of their own. These two statements assert nothing.
insert into public.members (display_name) values ('pgTAP Member')
  on conflict (display_name) do nothing;
insert into public.teams
  (season_id, member_id, sleeper_user_id, sleeper_roster_id, team_name)
values (
  (select id from public.seasons where year = 2026),
  (select id from public.members where display_name = 'pgTAP Member'),
  'pgtap-user', 999, 'pgTAP Team'
)
on conflict (season_id, sleeper_roster_id) do nothing;

select has_table('public', 'roster_holdings', 'roster_holdings table exists');
select has_table('public', 'team_season_state', 'team_season_state table exists');
select has_table('public', 'final_rosters', 'final_rosters table exists');
select has_table('public', 'player_projections', 'player_projections table exists');
select has_table('public', 'team_week_projections', 'team_week_projections table exists');
select has_table('public', 'nfl_state', 'nfl_state table exists');

select has_column('public', 'seasons', 'scoring_settings', 'seasons caches scoring_settings');
select has_column('public', 'seasons', 'waiver_budget', 'seasons caches waiver_budget');
select has_column(
  'public', 'members', 'sleeper_display_name',
  'members carries the Sleeper display name consumers fall back to'
);
select has_column('public', 'members', 'nickname', 'members carries the public nickname');

-- Every new public table is reachable by the anon key, so RLS being *on* is what
-- stands between the policies below and the whole table. A policy on a table with
-- RLS disabled reads as protection and is not.
select is(
  (select relrowsecurity from pg_class where oid = 'public.roster_holdings'::regclass),
  true, 'roster_holdings has row level security enabled'
);
select is(
  (select relrowsecurity from pg_class where oid = 'public.team_season_state'::regclass),
  true, 'team_season_state has row level security enabled'
);
select is(
  (select relrowsecurity from pg_class where oid = 'public.final_rosters'::regclass),
  true, 'final_rosters has row level security enabled'
);
select is(
  (select relrowsecurity from pg_class where oid = 'public.player_projections'::regclass),
  true, 'player_projections has row level security enabled'
);
select is(
  (select relrowsecurity from pg_class where oid = 'public.team_week_projections'::regclass),
  true, 'team_week_projections has row level security enabled'
);
select is(
  (select relrowsecurity from pg_class where oid = 'public.nfl_state'::regclass),
  true, 'nfl_state has row level security enabled'
);

select policies_are(
  'public', 'team_week_projections',
  array['Public team_week_projections are readable', 'Automation writes team_week_projections']
);
select policies_are(
  'public', 'final_rosters',
  array['Public final_rosters are readable', 'Automation writes final_rosters']
);

-- roster_holdings is the one public table automation_worker may delete from.
select isnt_empty(
  $$select 1 from information_schema.role_table_grants
     where grantee = 'automation_worker' and table_schema = 'public'
       and table_name = 'roster_holdings' and privilege_type = 'DELETE'$$,
  'automation_worker holds DELETE on public.roster_holdings'
);

-- final_rosters is included in what this must not find: a snapshot is permanent.
select is_empty(
  $$select table_name from information_schema.role_table_grants
     where grantee = 'automation_worker' and table_schema = 'public'
       and privilege_type = 'DELETE' and table_name <> 'roster_holdings'$$,
  'automation_worker holds DELETE on no other public table'
);

-- And a snapshot is never rewritten either: final_rosters is the one public table the
-- worker may insert into but not update, so the freeze cannot become an overwrite.
select table_privs_are(
  'public', 'final_rosters', 'automation_worker', array['SELECT', 'INSERT'],
  'automation_worker holds SELECT and INSERT on public.final_rosters and nothing else'
);

-- The five board tables are published to Realtime. Asserted as membership rather than
-- as the whole publication's contents: other migrations, and Studio on the hosted
-- project, may publish tables this task knows nothing about.
select bag_has(
  $$select tablename::text from pg_publication_tables
     where pubname = 'supabase_realtime' and schemaname = 'public'$$,
  $$values ('roster_holdings'), ('team_season_state'), ('final_rosters'),
           ('team_week_projections'), ('nfl_state')$$,
  'the five board tables are published to supabase_realtime'
);

-- player_projections is deliberately not published: a run touches thousands of rows.
select is_empty(
  $$select tablename::text from pg_publication_tables
     where pubname = 'supabase_realtime' and schemaname = 'public'
       and tablename = 'player_projections'$$,
  'player_projections is not published to supabase_realtime'
);

select is(
  (select relreplident from pg_class where oid = 'public.roster_holdings'::regclass),
  'f'::"char",
  'roster_holdings uses replica identity full so deletes carry the old row'
);

-- faab_remaining is generated, not writable.
insert into public.team_season_state
  (season_id, team_id, faab_budget, faab_used, synced_at)
values (
  (select id from public.seasons where year = 2026),
  (select id from public.teams where sleeper_roster_id = 999),
  1000, 250, now()
);
select is(
  (select faab_remaining from public.team_season_state order by id desc limit 1),
  750,
  'faab_remaining is generated from budget minus used'
);

-- nfl_state can only ever hold one row.
select throws_ok(
  $$insert into public.nfl_state (id, season, season_type, week, raw, synced_at)
    values (2, 2026, 'regular', 1, '{}'::jsonb, now())$$,
  '23514'::char(5),
  null,
  'nfl_state rejects any id but 1'
);

-- coverage_pct is a percentage, and the board sorts on the row it lives in, so the
-- bound is enforced by the column rather than by whoever computed it.
select throws_ok(
  $$insert into public.team_week_projections
      (season_id, team_id, week, projected_points, starter_slots, filled_slots,
       empty_slots, starters_projected, missing_projections, coverage_pct, computed_at)
    values (
      (select id from public.seasons where year = 2026),
      (select id from public.teams where sleeper_roster_id = 999),
      1, 100.5, 9, 9, 0, 9, 0, 150.0, now()
    )$$,
  '23514'::char(5),
  null,
  'team_week_projections rejects a coverage_pct outside 0-100'
);

-- The four natural keys every upsert in this data layer conflicts on. Each one is what
-- makes a sync idempotent, so each is asserted rather than assumed.
select col_is_unique(
  'public', 'roster_holdings', array['season_id', 'team_id', 'sleeper_player_id'],
  'one roster holding per team per player per season'
);
select col_is_unique(
  'public', 'team_season_state', array['season_id', 'team_id'],
  'one season state row per team per season'
);
select col_is_unique(
  'public', 'player_projections', array['season', 'week', 'sleeper_player_id'],
  'one projection per player per NFL week'
);
select col_is_unique(
  'public', 'team_week_projections', array['season_id', 'team_id', 'week'],
  'one team-week projection per team per week'
);

-- A team gets exactly one final roster, forever. The unique constraint is what makes
-- `on conflict do nothing` a permanent snapshot rather than a race.
select col_is_unique(
  'public', 'final_rosters', array['season_id', 'team_id'],
  'one final roster per team per season'
);

insert into public.final_rosters
  (season_id, team_id, eliminated_week, holdings, frozen_at)
values (
  (select id from public.seasons where year = 2026),
  (select id from public.teams where sleeper_roster_id = 999),
  3, '[]'::jsonb, now()
);
select throws_ok(
  $$insert into public.final_rosters
      (season_id, team_id, eliminated_week, holdings, frozen_at)
    values (
      (select id from public.seasons where year = 2026),
      (select id from public.teams where sleeper_roster_id = 999),
      4, '[]'::jsonb, now()
    )$$,
  '23505'::char(5),
  null,
  'a second final roster for the same team is rejected'
);

select * from finish();
rollback;
