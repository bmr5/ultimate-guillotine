begin;
select plan(6);
insert into public.historical_weekly_scores
  (season,week,sleeper_roster_id,sleeper_league_id,team_label,manager_label,points,
   filled_starting_slots,required_starters) values
  (2019,1,-96001,'test','Partial','Test',-1000,7,9),
  (2019,1,-96002,'test','Full','Test',-900,9,9),
  (2019,1,-96003,'test','Full tie','Test',-900,9,9),
  (2019,1,-96004,'test','Unknown','Test',-950,null,null);
set local role anon;
select is(public.get_weekly_score_records()->'lows'->0->'points','-1000'::jsonb,'original lows keep partial lineups');
select is(public.get_weekly_score_records()->'full_lineup_lows'->0->'points','-900'::jsonb,'full lineup lows exclude partial and unknown lineups');
select is(public.get_weekly_score_records()->'full_lineup_lows'->0->'rank','1'::jsonb,'filtered list ranks independently');
select is(public.get_weekly_score_records()->'full_lineup_lows'->1->'rank','1'::jsonb,'full lineup ties share a rank');
select is((select full_lineup from public.historical_weekly_scores where sleeper_roster_id=-96004),null::boolean,'unknown counts do not imply full lineups');
select is((select full_lineup from public.historical_weekly_scores where sleeper_roster_id=-96001),false,'partial slots stay partial');
reset role;
select * from finish();
rollback;
