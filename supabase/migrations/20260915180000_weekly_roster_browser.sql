-- A narrow read API for the all-team weekly archive. Private observations contain
-- source payloads; callers receive only these explicitly selected public fields.
-- No grants on private tables, live roster reads, or changes to archived evidence.
create function public.get_weekly_rosters(p_week_revision_id bigint)
returns table (
  team_id bigint,
  team_label text,
  manager_label text,
  points numeric,
  roster_at timestamptz,
  roster_coverage text,
  players jsonb
)
language sql stable security definer
set search_path = ''
as $$
  with revision as (
    select w.* from public.season_history_weeks w
    where w.id = p_week_revision_id and w.scope = 'production' and w.status = 'confirmed'
      and not exists (
        select 1 from public.season_history_weeks newer
        where newer.season_id = w.season_id and newer.week = w.week
          and newer.scope = 'production' and newer.revision > w.revision
      )
  ), results as (
    select distinct on (r.team_id) r.*
    from public.weekly_results r join revision w
      on w.season_id = r.season_id and w.week = r.week
    order by r.team_id, r.state_version desc
  ), cutoff as (
    -- Bind to the published revision's evidence, not a job's mutable cutoff pointer.
    select o.* from revision w
    join public.team_event_snapshots e on e.week_revision_id = w.id
      and e.event_type <> 'gulag_entered'
    join private.team_state_observations o on o.id = e.source_observation_id
      and o.season_id = w.season_id and o.week = w.week and o.scope = 'production'
    order by e.id limit 1
  ), scoring as (
    -- The publisher uses the last capture at or before checked_at. Later retries
    -- may contain roster moves or unconfirmed stat corrections and must not leak in.
    select o.* from private.team_state_observations o join revision w
      on w.season_id = o.season_id and w.week = o.week
    where o.scope = 'production' and o.observed_at <= w.checked_at
    order by o.observed_at desc, o.id desc limit 1
  ), teams as (
    select r.team_id, r.points, c.observed_at,
      c.payload->'teams'->r.team_id::text as saved,
      c.payload->'directory' as directory,
      s.payload->'directory' as scoring_directory,
      m.matchup,
      case when c.id is null then 'missing'
        when exists (
          select 1 from private.team_state_observations preceding
          where preceding.season_id = c.season_id and preceding.week = c.week
            and preceding.scope = 'production' and preceding.observed_at < c.observed_at
            and preceding.observed_at >= c.observed_at - interval '20 minutes'
        ) then 'complete' else 'partial' end as coverage
    from results r left join cutoff c on true left join scoring s on true
    left join lateral (
      select value as matchup from pg_catalog.jsonb_array_elements(s.payload->'matchups')
      where value->>'roster_id' = c.payload->'teams'->r.team_id::text->>'roster_id'
      -- If evidence doesn't agree with the official total, keep player scores unknown.
        and coalesce(nullif(value->>'custom_points', ''), value->>'points')::numeric = r.points
      limit 1
    ) m on true
    where r.is_final
  )
  select t.team_id, coalesce(t.saved->>'team_label', 'Team ' || t.team_id),
    t.saved->>'manager_label', t.points, t.observed_at,
    case when t.saved is null then 'missing' else t.coverage end,
    coalesce((
      select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'player_id', p.player_id,
        'player_label', coalesce(held.player->>'player_label',
          t.directory->p.player_id->>'full_name',
          t.scoring_directory->p.player_id->>'full_name', p.player_id),
        'position', coalesce(held.player->>'position',
          t.directory->p.player_id->>'position', t.scoring_directory->p.player_id->>'position'),
        'slot', held.player->>'slot',
        'started', lineup.ordinality is not null,
        'owned_at_cutoff', coalesce((held.player->>'owned')::boolean, false),
        'points', case when pg_catalog.jsonb_typeof(t.matchup->'players_points'->p.player_id) = 'number'
          then t.matchup->'players_points'->p.player_id else 'null'::jsonb end
      ) order by lineup.ordinality nulls last, held.player->>'player_label', p.player_id)
      from (
        select value->>'player_id' as player_id
        from pg_catalog.jsonb_array_elements(t.saved->'players')
        union
        select value from pg_catalog.jsonb_array_elements_text(t.matchup->'starters')
        where value <> '0'
      ) p
      left join lateral (
        select value as player from pg_catalog.jsonb_array_elements(t.saved->'players')
        where value->>'player_id' = p.player_id limit 1
      ) held on true
      left join lateral (
        select ordinality from pg_catalog.jsonb_array_elements_text(
          coalesce(t.matchup->'starters', t.saved->'starters')
        ) with ordinality where value = p.player_id limit 1
      ) lineup on true
    ), '[]'::jsonb)
  from teams t order by t.points desc, t.team_id;
$$;

revoke all on function public.get_weekly_rosters(bigint) from public;
grant execute on function public.get_weekly_rosters(bigint) to anon, authenticated, automation_worker;
