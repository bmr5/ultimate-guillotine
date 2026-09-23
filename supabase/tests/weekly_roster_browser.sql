begin;
select plan(14);

insert into public.seasons (id, year, sleeper_league_id, rules_version)
  overriding system value values (-98001, 2098, 'weekly-browser-test', 'test');
insert into public.members (id, display_name)
  overriding system value values (-98001, 'Weekly browser manager');
insert into public.teams (id, season_id, member_id, sleeper_user_id, sleeper_roster_id, team_name)
  overriding system value values (-98001, -98001, -98001, 'weekly-browser', 1, 'Renamed today');
insert into public.season_history_weeks
  (id, season_id, season, week, revision, scope, status, checked_at, rules_version)
  overriding system value values
  (-98001, -98001, 2098, 1, 1, 'production', 'confirmed', '2098-09-15 12:00Z', 'test'),
  (-98002, -98001, 2098, 1, 2, 'production', 'confirmed', '2098-09-15 13:00Z', 'test'),
  (-98003, -98001, 2098, 1, 99, 'test', 'confirmed', '2098-09-15 14:00Z', 'test');
insert into public.weekly_results (id, season_id, week, team_id, points, state_version, is_final)
  overriding system value values
  (-98001, -98001, 1, -98001, 100, 1, true),
  (-98002, -98001, 1, -98001, 150, 2, true);
insert into private.team_state_observations
  (id, season_id, scope, week, observed_at, content_hash, payload)
  overriding system value values
  (-98001, -98001, 'production', 1, '2098-09-15 03:20Z', 'preceding', '{}'),
  (-98002, -98001, 'production', 1, '2098-09-15 03:22Z', 'cutoff', '{
    "teams":{"-98001":{"roster_id":1,"team_label":"Saved team","manager_label":"Saved manager",
      "raw_roster":{"secret":"NEVER_PUBLIC"},"faab_remaining":999,
      "starters":["zero","departed"],"players":[
        {"player_id":"zero","player_label":"Zero scorer","position":"QB","slot":"starter","owned":true},
        {"player_id":"bench","player_label":"Bench player","position":"RB","slot":"bench","owned":true}]}},
    "directory":{"departed":{"full_name":"Departed starter","position":"WR"}}
  }'),
  (-98003, -98001, 'production', 1, '2098-09-15 13:00Z', 'confirmed-scoring', '{
    "matchups":[{"roster_id":1,"points":140,"custom_points":150,
      "starters":["departed","zero"],"players_points":{"zero":0,"departed":140}}]
  }'),
  (-98004, -98001, 'production', 1, '2098-09-15 14:00Z', 'later-live-data', '{
    "teams":{"-98001":{"team_label":"Later roster"}},
    "matchups":[{"roster_id":1,"points":300,"starters":["new"],"players_points":{"new":300}}]
  }');
insert into public.team_event_snapshots
  (id, week_revision_id, season_id, event_key, event_type, team_id, team_label,
   roster_coverage, money_coverage, source_observation_id)
  overriding system value values
  (-98001, -98002, -98001, 'qualification', 'gulag_qualified', -98001, 'Saved team', 'complete', 'missing', -98002);

set local role anon;
select is((select count(*) from public.get_weekly_rosters(-98002)), 1::bigint, 'anonymous browser reads current confirmed production week');
select is((select points from public.get_weekly_rosters(-98002)), 150::numeric, 'official corrected team total wins');
select is((select team_label from public.get_weekly_rosters(-98002)), 'Saved team', 'name comes from the pinned cutoff, not today');
select is((select roster_at from public.get_weekly_rosters(-98002)), '2098-09-15 03:22Z'::timestamptz, 'roster cutoff remains pinned');
select is((select roster_coverage from public.get_weekly_rosters(-98002)), 'complete', 'preceding capture establishes coverage');
select is((select jsonb_array_length(players) from public.get_weekly_rosters(-98002)), 3, 'keeps held players and scoring starters who left');
select is((select players->0->>'player_label' from public.get_weekly_rosters(-98002)), 'Departed starter', 'preserves scoring lineup order and historical names');
select is((select players->0->'owned_at_cutoff' from public.get_weekly_rosters(-98002)), 'false'::jsonb, 'departed starter is not represented as owned');
select is((select players->1->'points' from public.get_weekly_rosters(-98002)), '0'::jsonb, 'zero is preserved from confirmed scoring evidence');
select is((select players->2->'points' from public.get_weekly_rosters(-98002)), 'null'::jsonb, 'unrecorded bench points stay unknown');
select ok((select row_to_json(r)::text not like '%NEVER_PUBLIC%' and row_to_json(r)::text not like '%faab_remaining%'
  from public.get_weekly_rosters(-98002) r), 'raw source fields and money never enter the response');
select is((select count(*) from public.get_weekly_rosters(-98001)) +
  (select count(*) from public.get_weekly_rosters(-98003)), 0::bigint, 'old and test revisions cannot be requested');
reset role;
select ok(not has_table_privilege('anon', 'private.team_state_observations', 'SELECT'), 'private observations remain private');

insert into public.season_history_weeks
  (id, season_id, season, week, revision, scope, status, checked_at, rules_version)
  overriding system value values (-98004, -98001, 2098, 1, 3, 'production', 'retracted', '2098-09-15 15:00Z', 'test');
set local role anon;
select is((select count(*) from public.get_weekly_rosters(-98002)), 0::bigint, 'a retraction cannot resurrect an earlier confirmed week');
reset role;
select * from finish();
rollback;
