begin;
select plan(23);

-- (a) All nine public tables exist.
select has_table('public', 'seasons', 'public.seasons table exists');
select has_table('public', 'members', 'public.members table exists');
select has_table('public', 'teams', 'public.teams table exists');
select has_table('public', 'weekly_results', 'public.weekly_results table exists');
select has_table('public', 'league_events', 'public.league_events table exists');
select has_table('public', 'trades', 'public.trades table exists');
select has_table('public', 'trade_revisions', 'public.trade_revisions table exists');
select has_table('public', 'survival_snapshots', 'public.survival_snapshots table exists');
select has_table('public', 'recaps', 'public.recaps table exists');

-- (b) Row level security is enabled on all nine tables.
select ok(
  (select relrowsecurity from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname = 'seasons'),
  'public.seasons has row level security enabled'
);
select ok(
  (select relrowsecurity from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname = 'members'),
  'public.members has row level security enabled'
);
select ok(
  (select relrowsecurity from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname = 'teams'),
  'public.teams has row level security enabled'
);
select ok(
  (select relrowsecurity from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname = 'weekly_results'),
  'public.weekly_results has row level security enabled'
);
select ok(
  (select relrowsecurity from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname = 'league_events'),
  'public.league_events has row level security enabled'
);
select ok(
  (select relrowsecurity from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname = 'trades'),
  'public.trades has row level security enabled'
);
select ok(
  (select relrowsecurity from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname = 'trade_revisions'),
  'public.trade_revisions has row level security enabled'
);
select ok(
  (select relrowsecurity from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname = 'survival_snapshots'),
  'public.survival_snapshots has row level security enabled'
);
select ok(
  (select relrowsecurity from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname = 'recaps'),
  'public.recaps has row level security enabled'
);

-- (c) anon/authenticated hold select-only grants on the public tables: no grant of any
-- other privilege type, and exactly 18 SELECT grants (9 tables x 2 roles).
select is_empty(
  $$select grantee, table_schema, table_name, privilege_type
      from information_schema.role_table_grants
     where grantee in ('anon', 'authenticated')
       and table_schema = 'public'
       and privilege_type <> 'SELECT'$$,
  'anon and authenticated hold no non-SELECT grants on public tables'
);
select results_eq(
  $$select count(*)::int from information_schema.role_table_grants
     where grantee in ('anon', 'authenticated')
       and table_schema = 'public'
       and privilege_type = 'SELECT'
       and table_name in (
         'seasons', 'members', 'teams', 'weekly_results', 'league_events',
         'trades', 'trade_revisions', 'survival_snapshots', 'recaps'
       )$$,
  array[18],
  'anon and authenticated together hold exactly 18 SELECT grants on the nine public tables'
);

-- Existing policy-name, primary-key, and seed assertions.
select policies_are('public', 'seasons', array['Public seasons are readable']);
select col_is_pk('public', 'seasons', 'id', 'public.seasons.id is the primary key');
select results_eq('select count(*)::int from public.seasons where year = 2026', array[1]);

select * from finish();
rollback;
