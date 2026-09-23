begin;
select plan(6);
insert into public.historical_weekly_scores
  (season,week,sleeper_roster_id,sleeper_league_id,team_label,manager_label,points,
   filled_starting_slots,required_starters)
select 2019,1,-95000-i,'test','High '||i,'Test',
  10000 - case when i=11 then 10 else i end,9,9 from generate_series(1,12) i
union all
select 2019,1,-95100-i,'test','Low '||i,'Test',
  -10000 + case when i=11 then 10 else i end,9,9 from generate_series(1,12) i;
set local role anon;
select is(jsonb_array_length(public.get_weekly_score_records()->'highs'),11,'highs return ten ranks including boundary ties');
select is(jsonb_array_length(public.get_weekly_score_records()->'lows'),11,'lows return ten ranks including boundary ties');
select is(jsonb_array_length(public.get_weekly_score_records()->'full_lineup_lows'),11,'full-lineup lows return ten ranks including boundary ties');
select is(public.get_weekly_score_records()->'highs'->10->'rank','10'::jsonb,'last high is tied at tenth');
select is(public.get_weekly_score_records()->'lows'->10->'rank','10'::jsonb,'last low is tied at tenth');
select is(public.get_weekly_score_records()->'full_lineup_lows'->10->'rank','10'::jsonb,'last full-lineup low is tied at tenth');
reset role;
select * from finish();
rollback;
