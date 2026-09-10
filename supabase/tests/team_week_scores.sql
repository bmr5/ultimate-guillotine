-- public.team_week_scores: the live score the board shows beside the projection.
--
-- Its own file rather than more lines in league_data_layer.sql, so the table the score sync
-- writes is asserted next to nothing else and `select plan(n)` stays readable.
begin;
select plan(11);

-- `supabase db reset` seeds only public.seasons, so the row-level assertions below need a member
-- and a team of their own. These two statements assert nothing, and they are the same pair
-- league_data_layer.sql inserts — `on conflict do nothing` makes running both files safe.
insert into public.members (display_name) values ('pgTAP Member')
  on conflict (display_name) do nothing;
insert into public.teams
  (season_id, member_id, sleeper_user_id, sleeper_roster_id, team_name)
values (
  (select id from public.seasons where year = 2026),
  (select id from public.members where display_name = 'pgTAP Member'),
  'pgtap-user', 999, 'pgTAP Team'
)
on conflict (season_id, sleeper_roster_id) do nothing;

select has_table('public', 'team_week_scores', 'team_week_scores table exists');

-- The three columns that carry the score itself. `points` is the figure the card shows,
-- `players_points` is what a roster row reads its live number out of, and `starters` is the
-- lineup order Sleeper reports — none of them derivable from the other two.
select has_column('public', 'team_week_scores', 'points', 'team_week_scores carries the points');
select has_column(
  'public', 'team_week_scores', 'players_points',
  'team_week_scores carries the per-player points map'
);
select has_column(
  'public', 'team_week_scores', 'starters',
  'team_week_scores carries the lineup Sleeper reported'
);
select has_column(
  'public', 'team_week_scores', 'synced_at',
  'team_week_scores carries the stamp the board reads instead of computed_at'
);

-- The table is reachable by the anon key, so RLS being *on* is what stands between the policy
-- below and the whole table. A policy on a table with RLS disabled reads as protection and is not.
select is(
  (select relrowsecurity from pg_class where oid = 'public.team_week_scores'::regclass),
  true, 'team_week_scores has row level security enabled'
);

select policies_are(
  'public', 'team_week_scores',
  array['Public team_week_scores are readable', 'Automation writes team_week_scores']
);

-- No DELETE. A week's row is rewritten in place every minute of a game window; there is never
-- anything to evict, and `roster_holdings` stays the one public table the worker may delete from.
select table_privs_are(
  'public', 'team_week_scores', 'automation_worker', array['SELECT', 'INSERT', 'UPDATE'],
  'automation_worker holds SELECT, INSERT and UPDATE on public.team_week_scores and nothing else'
);

-- Published to Realtime: a score that only reached an open board on the next poll is the
-- "it should always be realtime" complaint this table exists to answer. Asserted as membership
-- rather than as the publication's whole contents, which other migrations also write to.
select bag_has(
  $$select tablename::text from pg_publication_tables
     where pubname = 'supabase_realtime' and schemaname = 'public'$$,
  $$values ('team_week_scores')$$,
  'team_week_scores is published to supabase_realtime'
);

-- The natural key every upsert conflicts on, which is what makes the sync idempotent: it fires
-- once a minute through a game window and must rewrite the same 18 rows, not append to them.
select col_is_unique(
  'public', 'team_week_scores', array['season_id', 'team_id', 'week'],
  'one score row per team per week'
);

-- The two jsonb/array columns default to empty rather than null, so a team Sleeper reports with
-- no lineup yet still reads as "nobody started" instead of as an absent map the board must guard.
insert into public.team_week_scores (season_id, team_id, week, points, synced_at)
values (
  (select id from public.seasons where year = 2026),
  (select id from public.teams where sleeper_roster_id = 999),
  1, 87.32, now()
);
select is(
  (select (players_points, starters)::text from public.team_week_scores
    where week = 1 order by id desc limit 1),
  '({},{})',
  'players_points and starters default to empty, never null'
);

select * from finish();
rollback;
