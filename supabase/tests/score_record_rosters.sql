begin;
select plan(5);
insert into public.historical_weekly_scores
  (season,week,sleeper_roster_id,sleeper_league_id,team_label,manager_label,points,roster) values
  (2019,1,-94001,'test','Saved name','Saved manager',22.5,
   '{"starters":[{"player_id":null,"player_label":"Empty slot","position":null,"slot":"QB","points":0},{"player_id":"a","player_label":"Saved player","position":"RB","slot":"RB","points":22.5}],"bench":[{"player_id":"b","player_label":"Bench player","position":"WR","slot":"Bench","points":40}]}');
set local role anon;
select is(public.get_score_record_roster('sleeper:2019:1:-94001')->>'team_label','Saved name','reads the exact archived team/week');
select is(public.get_score_record_roster('sleeper:2019:1:-94001')->'roster'->'starters'->0->'player_id','null'::jsonb,'retains empty starting slots');
select is(public.get_score_record_roster('sleeper:2019:1:-94001')->'roster'->'bench'->0->'points','40'::jsonb,'bench scoring stays separate');
select is(public.get_score_record_roster('sleeper:2019:2:-94001'),null::jsonb,'does not substitute another week');
select is(public.get_score_record_roster('invalid-key'),null::jsonb,'invalid keys disclose nothing');
reset role;
select * from finish();
rollback;
