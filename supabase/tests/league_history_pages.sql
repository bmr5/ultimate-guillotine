begin;
select plan(31);

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
-- A signed-in commissioner reads these pages through the same anon-shaped grant: the loaders
-- write from the worker role, never from a browser session.
select table_privs_are(
  'public', 'trade_catalog', 'authenticated', array['SELECT'],
  'authenticated may only read trade_catalog'
);
select table_privs_are(
  'public', 'season_results', 'authenticated', array['SELECT'],
  'authenticated may only read season_results'
);
select table_privs_are(
  'public', 'trade_catalog', 'automation_worker', array['SELECT', 'INSERT', 'UPDATE'],
  'automation_worker holds SELECT, INSERT and UPDATE on trade_catalog and nothing else'
);
select table_privs_are(
  'public', 'season_results', 'automation_worker', array['SELECT', 'INSERT', 'UPDATE'],
  'automation_worker holds SELECT, INSERT and UPDATE on season_results and nothing else'
);

-- A bad confidence or source must be refused by the database, not only by the loader.
select throws_ok(
  $$insert into public.trade_catalog
      (catalog_id, season, week, trade_type, structure, party_count, confidence, loaded_at)
    values ('bad-conf', 2025, 3, 'trade', '1-for-1', 2, 'certain', now())$$,
  '23514'::char(5), null, 'confidence is constrained to high/medium/low'
);
select throws_ok(
  $$insert into public.trade_catalog
      (catalog_id, season, week, trade_type, structure, party_count, confidence, source,
       loaded_at)
    values ('bad-src', 2025, 3, 'trade', '1-for-1', 2, 'high', 'guessed', now())$$,
  '23514'::char(5), null, 'source is constrained to catalog/registered'
);

-- A trade that sits in no week and on no date cannot be sorted or filtered by the pages.
select throws_ok(
  $$insert into public.trade_catalog
      (catalog_id, season, trade_type, structure, party_count, confidence, loaded_at)
    values ('no-when', 2025, 'trade', '1-for-1', 2, 'high', now())$$,
  '23514'::char(5), null, 'a catalog row carries a week or a date'
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
  (catalog_id, season, week, trade_type, structure, party_count, confidence, loaded_at)
values ('dup-1', 2025, 3, 'trade', '1-for-1', 2, 'high', now());
select throws_ok(
  $$insert into public.trade_catalog
      (catalog_id, season, week, trade_type, structure, party_count, confidence, loaded_at)
    values ('dup-1', 2025, 3, 'trade', '1-for-1', 2, 'high', now())$$,
  '23505'::char(5), null, 'catalog_id is unique'
);
insert into public.season_results (season, loaded_at) values (1999, now());
select throws_ok(
  $$insert into public.season_results (season, loaded_at) values (1999, now())$$,
  '23505'::char(5), null, 'season is unique'
);

-- Neither table stores a person's name: parties and champions are public.members ids.
select has_column('public', 'trade_catalog', 'party_member_ids', 'parties are stored as ids');

-- The one chat-derived field either table carries, by Ben's decision of 2026-09-10. Nullable,
-- because a record with no text must render as nothing rather than as a placeholder -- so the
-- column is asserted nullable rather than merely present.
select has_column(
  'public', 'trade_catalog', 'announcement', 'the trade announcement has a column'
);
select col_is_null(
  'public', 'trade_catalog', 'announcement',
  'a trade the catalog has no announcement for carries none'
);
select has_column(
  'public', 'season_results', 'champion_member_id', 'champions are stored as ids'
);

-- `assets` is jsonb on an anon-readable table, so its shape is closed rather than open: the
-- three kinds the loader emits are accepted, and a fourth kind, a stray key, or a free-text
-- condition label is refused by the database.
select lives_ok(
  $$insert into public.trade_catalog
      (catalog_id, season, week, trade_type, structure, party_count, confidence, assets,
       loaded_at)
    values ('assets-ok', 2025, 3, 'trade', '1-for-1', 2, 'high',
      '[{"kind": "player", "sleeper_player_id": "4034", "name": "A Player",
         "position": "RB", "from_party": 0, "to_party": 1},
        {"kind": "faab", "amount": 12, "from_party": 1, "to_party": 0},
        {"kind": "condition", "label": "return_after_week", "week": 9}]'::jsonb,
      now())$$,
  'the three asset shapes the loader emits are accepted'
);
select throws_ok(
  $$insert into public.trade_catalog
      (catalog_id, season, week, trade_type, structure, party_count, confidence, assets,
       loaded_at)
    values ('assets-note', 2025, 3, 'trade', '1-for-1', 2, 'high',
      '[{"kind": "note", "text": "he said he would give him back"}]'::jsonb, now())$$,
  '23514'::char(5), null, 'an asset kind outside player/faab/condition is refused'
);
select throws_ok(
  $$insert into public.trade_catalog
      (catalog_id, season, week, trade_type, structure, party_count, confidence, assets,
       loaded_at)
    values ('assets-extra', 2025, 3, 'trade', '1-for-1', 2, 'high',
      '[{"kind": "player", "sleeper_player_id": "4034", "name": "A Player",
         "position": "RB", "quote": "he said he would give him back"}]'::jsonb, now())$$,
  '23514'::char(5), null, 'an asset with a key outside its shape is refused'
);
select throws_ok(
  $$insert into public.trade_catalog
      (catalog_id, season, week, trade_type, structure, party_count, confidence, assets,
       loaded_at)
    values ('assets-prose', 2025, 3, 'trade', '1-for-1', 2, 'high',
      '[{"kind": "condition", "label": "handshake deal, he owes me one"}]'::jsonb, now())$$,
  '23514'::char(5), null, 'a condition label outside the closed set is refused'
);

-- `eliminations` is the other open jsonb column, closed the same way.
select lives_ok(
  $$insert into public.season_results (season, eliminations, loaded_at)
    values (1998,
      '[{"week": 2, "order": 1, "member_id": null, "gulag_out": 2, "pool_out": 0,
         "remaining": 17, "note": null},
        {"week": 3, "order": 2, "member_id": null, "gulag_out": 1, "pool_out": null,
         "remaining": 16, "note": "double header"}]'::jsonb,
      now())$$,
  'the elimination shape the records loader emits is accepted'
);
select throws_ok(
  $$insert into public.season_results (season, eliminations, loaded_at)
    values (1997, '[{"week": 2, "order": 1, "excerpt": "SENTINEL"}]'::jsonb, now())$$,
  '23514'::char(5), null, 'an elimination entry with a key outside its shape is refused'
);
select throws_ok(
  $$insert into public.season_results (season, eliminations, loaded_at)
    values (1996,
      ('[{"week": 2, "order": 1, "note": "' || repeat('x', 121) || '"}]')::jsonb, now())$$,
  '23514'::char(5), null, 'an elimination note longer than 120 characters is refused'
);

select * from finish();
rollback;
