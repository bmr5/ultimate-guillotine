alter table public.historical_weekly_scores add column roster jsonb
  check (roster is null or jsonb_typeof(roster) = 'object');

-- Detail reads are separate from the small leaderboards. Exact key matching avoids
-- parsing untrusted input. Current-season reads retain the existing revision gates.
create function public.get_score_record_roster(p_record_key text)
returns jsonb language sql stable security invoker set search_path = '' as $$
  select pg_catalog.jsonb_build_object(
    'key',p_record_key,'season',h.season,'week',h.week,'team_label',h.team_label,
    'manager_label',h.manager_label,'points',h.points,'roster',h.roster,'roster_at',null
  ) from public.historical_weekly_scores h
  where 'sleeper:' || h.season || ':' || h.week || ':' || h.sleeper_roster_id = p_record_key
  union all
  select pg_catalog.jsonb_build_object(
    'key',p_record_key,'season',w.season,'week',w.week,'team_label',r.team_label,
    'manager_label',r.manager_label,'points',r.points,'roster_at',r.roster_at,
    'roster',case when r.roster_coverage = 'missing' then null else pg_catalog.jsonb_build_object(
      'starters',coalesce((select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'player_id',p->>'player_id','player_label',p->>'player_label','position',p->>'position',
        'slot','Starter','points',p->'points') order by ordinal)
        from pg_catalog.jsonb_array_elements(r.players) with ordinality as players(p,ordinal)
        where (p->>'started')::boolean),'[]'::jsonb) ||
        coalesce((select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'player_id',null,'player_label','Empty slot','position',null,'slot','Starter','points',0))
          from pg_catalog.generate_series(1,greatest(0, required.slots - (
            select count(*)::int from pg_catalog.jsonb_array_elements(r.players) p
            where (p->>'started')::boolean
          )))),'[]'::jsonb),
      'bench',coalesce((select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'player_id',p->>'player_id','player_label',p->>'player_label','position',p->>'position',
        'slot',coalesce(p->>'slot','Bench'),'points',p->'points') order by ordinal)
        from pg_catalog.jsonb_array_elements(r.players) with ordinality as players(p,ordinal)
        where not (p->>'started')::boolean),'[]'::jsonb)
    ) end
  ) from public.season_history_current_weeks w
  join public.seasons s on s.year=w.season
  cross join lateral public.get_weekly_rosters(w.id) r
  cross join lateral (select count(*)::int as slots
    from pg_catalog.jsonb_array_elements_text(s.roster_positions) slot
    where slot not in ('BN','IR','TAXI')) required
  where w.status='confirmed' and w.season>=2026
    and 'archive:' || w.season || ':' || w.week || ':' || r.team_id = p_record_key;
$$;
revoke all on function public.get_score_record_roster(text) from public;
grant execute on function public.get_score_record_roster(text) to anon, authenticated, automation_worker;
