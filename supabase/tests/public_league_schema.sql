begin;
select plan(5);
select has_table('public', 'seasons', 'public.seasons table exists');
select has_table('public', 'league_events', 'public.league_events table exists');
select policies_are('public', 'seasons', array['Public seasons are readable']);
select col_is_pk('public', 'seasons', 'id', 'public.seasons.id is the primary key');
select results_eq('select count(*)::int from public.seasons where year = 2026', array[1]);
select * from finish();
rollback;
