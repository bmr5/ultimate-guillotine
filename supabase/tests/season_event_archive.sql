begin;
select plan(12);

insert into public.seasons (id, year, sleeper_league_id, rules_version)
  overriding system value values (-99001, 2099, 'archive-test', 'archive-test');
insert into public.members (id, display_name)
  overriding system value values (-99001, 'Archive test manager');
insert into public.teams (id, season_id, member_id, sleeper_user_id, sleeper_roster_id, team_name)
  overriding system value values (-99001, -99001, -99001, 'archive-test', 1, 'Archive test team');
insert into public.season_history_weeks
  (id, season_id, season, week, revision, scope, status, remaining_teams, checked_at, rules_version)
  overriding system value values
  (-99001, -99001, 2099, 1, 1, 'production', 'confirmed', 18, now(), 'test'),
  (-99002, -99001, 2099, 1, 2, 'production', 'confirmed', 18, now(), 'test'),
  (-99003, -99001, 2099, 1, 99, 'test', 'confirmed', 18, now(), 'test');
insert into public.team_event_snapshots
  (id, week_revision_id, season_id, event_key, event_type, team_id, team_label, roster_coverage, money_coverage)
  overriding system value values
  (-99001, -99001, -99001, 'qualification', 'gulag_qualified', -99001, 'Old name', 'complete', 'missing'),
  (-99002, -99002, -99001, 'qualification', 'gulag_qualified', -99001, 'Correct name', 'complete', 'missing'),
  (-99003, -99003, -99001, 'qualification', 'gulag_qualified', -99001, 'Test name', 'complete', 'missing');
insert into public.team_event_players (snapshot_id, player_id, player_label, started, owned_at_cutoff) values
  (-99001, 'player-old', 'Old player', true, true),
  (-99002, 'player-correct', 'Correct player', true, true),
  (-99003, 'player-test', 'Test player', true, true);

set local role anon;
select is((select id from public.season_history_current_weeks where season = 2099), -99002::bigint,
  'latest production revision wins even when a test revision is newer');
select is((select count(*) from public.season_history_weeks where season = 2099), 2::bigint,
  'test weeks are excluded by RLS');
select is((select team_label from public.season_history_current_events where week_revision_id = -99002), 'Correct name',
  'current events expose the corrected snapshot');
select is((select count(*) from public.season_history_current_events where week_revision_id in (-99001, -99003)), 0::bigint,
  'old and test snapshots never enter the current view');
select is((select player_id from public.season_history_current_players where snapshot_id = -99002), 'player-correct',
  'current roster follows the selected correction');
select is((select count(*) from public.team_event_players where snapshot_id = -99003), 0::bigint,
  'test player rows cannot be read even from the underlying table');
select ok(not has_table_privilege('anon', 'public.team_event_snapshots', 'INSERT'), 'browser cannot publish outcomes');
reset role;
select ok(not has_table_privilege('automation_worker', 'public.team_event_snapshots', 'UPDATE'), 'worker cannot rewrite old snapshots');

insert into public.season_history_weeks
  (id, season_id, season, week, revision, scope, status, checked_at, rules_version)
  overriding system value values (-99004, -99001, 2099, 1, 3, 'production', 'retracted', now(), 'test');
set local role anon;
select is((select count(*) from public.season_history_current_events where week_revision_id in (-99001, -99002, -99004)), 0::bigint,
  'retraction removes the current events without resurrecting an older revision');
reset role;

select throws_ok($$insert into public.team_event_snapshots
  (week_revision_id, season_id, event_key, event_type, team_id, team_label, roster_coverage, money_coverage)
  values (-99002, -99001, 'bad-cut', 'eliminated', -99001, 'Bad cut', 'missing', 'missing')$$,
  '23514'::char(5), null, 'terminal cuts require an explicit elimination reason');
select throws_ok($$insert into public.team_event_snapshots
  (week_revision_id, season_id, event_key, event_type, team_id, team_label, roster_coverage, money_coverage)
  values (-99002, -99001, 'bad-money', 'gulag_entered', -99001, 'Bad money', 'missing', 'complete')$$,
  '23514'::char(5), null, 'complete money coverage requires a balance and as-of timestamp');
select throws_ok($$insert into public.season_history_weeks
  (season_id, season, week, revision, scope, status, checked_at, rules_version)
  values (-99001, 2025, 1, 1, 'production', 'confirmed', now(), 'test')$$,
  '23514'::char(5), null, 'pre-2026 history cannot enter this archive');
select * from finish();
rollback;
