begin;
select plan(17);

select has_table('public', 'trade_catalog', 'trade_catalog table exists');
select has_table('public', 'season_results', 'season_results table exists');

select is(
  (select relrowsecurity from pg_class where oid = 'public.trade_catalog'::regclass),
  true, 'trade_catalog has row level security enabled'
);
select is(
  (select relrowsecurity from pg_class where oid = 'public.season_results'::regclass),
  true, 'season_results has row level security enabled'
);

select policies_are(
  'public', 'trade_catalog',
  array['Public trade_catalog are readable', 'Automation writes trade_catalog']
);
select policies_are(
  'public', 'season_results',
  array['Public season_results are readable', 'Automation writes season_results']
);

-- History is not retracted from a laptop: roster_holdings stays the only deletable table.
select is_empty(
  $$select table_name from information_schema.role_table_grants
     where grantee = 'automation_worker' and table_schema = 'public'
       and privilege_type = 'DELETE' and table_name <> 'roster_holdings'$$,
  'automation_worker holds DELETE on no history table'
);
select table_privs_are(
  'public', 'trade_catalog', 'anon', array['SELECT'],
  'anon may only read trade_catalog'
);
select table_privs_are(
  'public', 'season_results', 'anon', array['SELECT'],
  'anon may only read season_results'
);

-- A bad confidence or source must be refused by the database, not only by the loader.
select throws_ok(
  $$insert into public.trade_catalog
      (catalog_id, season, trade_type, structure, party_count, confidence, loaded_at)
    values ('bad-conf', 2025, 'trade', '1-for-1', 2, 'certain', now())$$,
  '23514'::char(5), null, 'confidence is constrained to high/medium/low'
);
select throws_ok(
  $$insert into public.trade_catalog
      (catalog_id, season, trade_type, structure, party_count, confidence, source, loaded_at)
    values ('bad-src', 2025, 'trade', '1-for-1', 2, 'high', 'guessed', now())$$,
  '23514'::char(5), null, 'source is constrained to catalog/registered'
);

-- The natural keys the loaders upsert on. Asserted as constraints, so `on conflict`
-- has something to conflict on, and exercised, so the refusal is real.
select col_is_unique(
  'public', 'trade_catalog', array['catalog_id'],
  'one catalog row per classification record id'
);
select col_is_unique(
  'public', 'season_results', array['season'],
  'one results row per season year'
);

insert into public.trade_catalog
  (catalog_id, season, trade_type, structure, party_count, confidence, loaded_at)
values ('dup-1', 2025, 'trade', '1-for-1', 2, 'high', now());
select throws_ok(
  $$insert into public.trade_catalog
      (catalog_id, season, trade_type, structure, party_count, confidence, loaded_at)
    values ('dup-1', 2025, 'trade', '1-for-1', 2, 'high', now())$$,
  '23505'::char(5), null, 'catalog_id is unique'
);
insert into public.season_results (season, loaded_at) values (1999, now());
select throws_ok(
  $$insert into public.season_results (season, loaded_at) values (1999, now())$$,
  '23505'::char(5), null, 'season is unique'
);

-- Neither table stores a person's name: parties and champions are public.members ids.
select has_column('public', 'trade_catalog', 'party_member_ids', 'parties are stored as ids');
select has_column(
  'public', 'season_results', 'champion_member_id', 'champions are stored as ids'
);

select * from finish();
rollback;
