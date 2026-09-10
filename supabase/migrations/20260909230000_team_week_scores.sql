-- Live scores: what each team has actually scored so far this week, beside the projection the
-- board already carries. Ben: "the team cards on the board should show their current score right
-- next to their projected. Also why does it show that it updated at 9:30PM it should always be
-- realtime!" The `Updated` stamp was `team_week_projections.computed_at` and there was no score
-- sync at all; this is the table the new one writes and the board's stamp then reads.
--
-- Same shape as `public.team_week_projections` in 20260909151435_league_data_layer.sql: identity
-- key, created_at, season/team/week natural key, RLS on, select-only for anon/authenticated, an
-- "Automation writes <table>" policy for automation_worker, and select/insert/update for the
-- worker with no delete — a week's row is rewritten every minute of a game window, never removed.
create table public.team_week_scores (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  team_id bigint not null references public.teams (id),
  week int not null,
  -- Sleeper's own `points` for the matchup row: the league's scoring already applied, so this
  -- is not re-derived from `players_points` here. numeric(8, 2) matches projected_points, so a
  -- score and a projection sit on the same card without one carrying more precision.
  points numeric(8, 2) not null,
  -- sleeper_player_id -> points, verbatim from the matchup row. It covers the starters only --
  -- nine entries for nine starters -- so the roster panel has a live number for a starter and
  -- nothing for a bench player, which is why it is stored rather than derived from the lineup.
  players_points jsonb not null default '{}',
  -- The lineup as Sleeper reports it, in slot order. Kept as its own column rather than being
  -- read back out of `players_points`: the map is unordered and says nothing about who started.
  starters text[] not null default '{}',
  -- When the sync last wrote this row. This is what the board's `Scores updated` stamp reads,
  -- and it moves every run, unlike `computed_at`, which only moves when a projection is recomputed.
  synced_at timestamptz not null,
  unique (season_id, team_id, week)
);
create index team_week_scores_season_week_idx on public.team_week_scores (season_id, week);

alter table public.team_week_scores enable row level security;

revoke all on public.team_week_scores from anon, authenticated;
grant select on public.team_week_scores to anon, authenticated;

create policy "Public team_week_scores are readable" on public.team_week_scores
  for select using (true);
create policy "Automation writes team_week_scores" on public.team_week_scores
  for all to automation_worker using (true) with check (true);

-- No delete grant. `roster_holdings` is still the one public table the worker may delete from:
-- a score row is upserted in place for the life of the week and there is nothing to evict.
grant select, insert, update on public.team_week_scores to automation_worker;
grant usage, select on all sequences in schema public to automation_worker;

-- Realtime. This is the whole point of the table being written rather than derived: a score
-- change has to reach an open board without a refresh, which is the complaint that started this.
-- One row per team per week and one write per run, so the publication carries ~18 rows a minute
-- in a game window — the same order as `team_week_projections`, and nothing like the thousands
-- `player_projections` would push, which is why that one is still excluded.
--
-- Both the publication and the membership are added conditionally, so a database that already
-- carries them (a hosted project where Realtime was switched on from Studio) survives unchanged.
do $$
begin
  if not exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    create publication supabase_realtime;
  end if;
end
$$;

do $$
begin
  if not exists (
    select 1 from pg_publication_tables
     where pubname = 'supabase_realtime'
       and schemaname = 'public'
       and tablename = 'team_week_scores'
  ) then
    alter publication supabase_realtime add table public.team_week_scores;
  end if;
end
$$;
