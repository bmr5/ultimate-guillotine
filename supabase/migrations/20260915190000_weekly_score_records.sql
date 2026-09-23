create table public.historical_weekly_scores (
  season int not null check (season between 2019 and 2025),
  week int not null check (week between 1 and 17),
  sleeper_roster_id int not null,
  sleeper_league_id text not null,
  team_label text not null check (length(team_label) between 1 and 120),
  manager_label text not null check (length(manager_label) between 1 and 120),
  points numeric(8,2) not null,
  loaded_at timestamptz not null default now(),
  primary key (season, week, sleeper_roster_id)
);
alter table public.historical_weekly_scores enable row level security;
revoke all on public.historical_weekly_scores from anon, authenticated;
grant select on public.historical_weekly_scores to anon, authenticated;
grant select, insert, update on public.historical_weekly_scores to automation_worker;
create policy "Public historical scores" on public.historical_weekly_scores for select using (true);
create policy "Worker imports historical scores" on public.historical_weekly_scores
  for all to automation_worker using (true) with check (true);

-- Current-season scores follow confirmed revisions, including later corrections
-- and retractions. The same frozen team labels as the weekly roster browser apply.
create function public.get_weekly_score_records()
returns jsonb language sql stable security invoker set search_path = '' as $$
  with scores as materialized (
    select h.season,h.week,h.team_label,h.manager_label,h.points,
      'sleeper:' || h.season || ':' || h.week || ':' || h.sleeper_roster_id as key
    from public.historical_weekly_scores h
    union all
    select w.season,w.week,r.team_label,r.manager_label,r.points,
      'archive:' || w.season || ':' || w.week || ':' || r.team_id as key
    from public.season_history_current_weeks w
    cross join lateral public.get_weekly_rosters(w.id) r
    where w.status = 'confirmed' and w.season >= 2026
  ), ranked as (
    select *,rank() over (order by points desc) as high_rank,
      rank() over (order by points) as low_rank from scores
  )
  select pg_catalog.jsonb_build_object(
    'highs',coalesce((select pg_catalog.jsonb_agg(
      (pg_catalog.to_jsonb(r) - 'low_rank' - 'high_rank') || pg_catalog.jsonb_build_object('rank',high_rank)
      order by points desc,season,week,key) from ranked r where high_rank <= 5),'[]'::jsonb),
    'lows',coalesce((select pg_catalog.jsonb_agg(
      (pg_catalog.to_jsonb(r) - 'low_rank' - 'high_rank') || pg_catalog.jsonb_build_object('rank',low_rank)
      order by points,season,week,key) from ranked r where low_rank <= 5),'[]'::jsonb),
    'coverage',coalesce((select pg_catalog.jsonb_agg(pg_catalog.to_jsonb(c) order by season) from (
      select season,count(distinct week) as weeks,count(*) as scores from scores group by season
    ) c),'[]'::jsonb)
  );
$$;
revoke all on function public.get_weekly_score_records() from public;
grant execute on function public.get_weekly_score_records() to anon, authenticated, automation_worker;
