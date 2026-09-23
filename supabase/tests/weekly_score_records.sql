begin;
select plan(7);
insert into public.historical_weekly_scores
  (season,week,sleeper_roster_id,sleeper_league_id,team_label,manager_label,points) values
  (2019,1,-97001,'test','Tie one','Test',10000),
  (2019,1,-97002,'test','Tie two','Test',10000),
  (2019,1,-97003,'test','Third','Test',9000),
  (2019,1,-97004,'test','Fourth','Test',8000),
  (2019,1,-97005,'test','Fifth one','Test',7000),
  (2019,1,-97006,'test','Fifth two','Test',7000),
  (2019,1,-97007,'test','Low','Test',-1000);
set local role anon;
select is((select count(*) from jsonb_array_elements(public.get_weekly_score_records()->'highs') r where r->>'rank'='5'),2::bigint,'includes every tie at the fifth rank');
select is(public.get_weekly_score_records()->'highs'->0->'points','10000.00'::jsonb,'highest score first');
select is(public.get_weekly_score_records()->'highs'->1->'rank','1'::jsonb,'tied scores share a rank');
select is(public.get_weekly_score_records()->'highs'->2->'rank','3'::jsonb,'rank after a tie skips places');
select is(public.get_weekly_score_records()->'lows'->0->'points','-1000.00'::jsonb,'valid negative scores can be low records');
select ok(exists(select 1 from jsonb_array_elements(public.get_weekly_score_records()->'coverage') c
  where c->>'season'='2019' and (c->>'scores')::int >= 7),'reports actual historical coverage');
select ok(not has_table_privilege('anon','public.historical_weekly_scores','INSERT'),'browser cannot change records');
reset role;
select * from finish();
rollback;
