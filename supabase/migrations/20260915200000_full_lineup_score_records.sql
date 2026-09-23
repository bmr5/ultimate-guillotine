-- Unknown historical lineup counts stay null until reimported from Sleeper.
alter table public.historical_weekly_scores
  add column filled_starting_slots int check (filled_starting_slots >= 0),
  add column required_starters int check (required_starters > 0),
  add column full_lineup boolean generated always as
    (filled_starting_slots = required_starters) stored;

create or replace function public.get_weekly_score_records()
returns jsonb language sql stable security invoker set search_path = '' as $$
  with scores as materialized (
    select h.season,h.week,h.team_label,h.manager_label,h.points,h.full_lineup,
      'sleeper:' || h.season || ':' || h.week || ':' || h.sleeper_roster_id as key
    from public.historical_weekly_scores h
    union all
    select w.season,w.week,r.team_label,r.manager_label,r.points,
      -- Count the saved scoring lineup against this season's required slots.
      -- Unknown settings never qualify a lineup as full.
      (select count(distinct p->>'player_id') from pg_catalog.jsonb_array_elements(r.players) p
       where (p->>'started')::boolean) = required.slots and required.slots > 0 as full_lineup,
      'archive:' || w.season || ':' || w.week || ':' || r.team_id as key
    from public.season_history_current_weeks w
    cross join lateral public.get_weekly_rosters(w.id) r
    join public.seasons season on season.year = w.season
    cross join lateral (
      select count(*) as slots from pg_catalog.jsonb_array_elements_text(season.roster_positions) slot
      where slot not in ('BN','IR','TAXI')
    ) required
    where w.status = 'confirmed' and w.season >= 2026
  ), ranked as (
    select *,rank() over (order by points desc) as high_rank,
      rank() over (order by points) as low_rank from scores
  ), full_ranked as (
    select *,rank() over (order by points) as full_rank from scores where full_lineup is true
  )
  select pg_catalog.jsonb_build_object(
    'highs',coalesce((select pg_catalog.jsonb_agg(
      (pg_catalog.to_jsonb(r) - 'low_rank' - 'high_rank' - 'full_lineup') || pg_catalog.jsonb_build_object('rank',high_rank)
      order by points desc,season,week,key) from ranked r where high_rank <= 5),'[]'::jsonb),
    'lows',coalesce((select pg_catalog.jsonb_agg(
      (pg_catalog.to_jsonb(r) - 'low_rank' - 'high_rank' - 'full_lineup') || pg_catalog.jsonb_build_object('rank',low_rank)
      order by points,season,week,key) from ranked r where low_rank <= 5),'[]'::jsonb),
    'full_lineup_lows',coalesce((select pg_catalog.jsonb_agg(
      (pg_catalog.to_jsonb(r) - 'full_rank' - 'full_lineup') || pg_catalog.jsonb_build_object('rank',full_rank)
      order by points,season,week,key) from full_ranked r where full_rank <= 5),'[]'::jsonb),
    'coverage',coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(c) order by season) from (
      select season,count(distinct week) as weeks,count(*) as scores from scores group by season
    ) c),'[]'::jsonb)
  );
$$;
revoke all on function public.get_weekly_score_records() from public;
grant execute on function public.get_weekly_score_records() to anon, authenticated, automation_worker;
