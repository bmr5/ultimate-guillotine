begin;
select plan(9);

-- (a) The players and member_aliases tables exist.
select has_table('public', 'players', 'players table exists');
select has_table('private', 'member_aliases', 'member aliases table exists');

-- (b) The trade fingerprint columns exist.
select has_column('public', 'trade_revisions', 'semantic_fingerprint', 'fingerprint column exists');
select has_column('public', 'trades', 'context_key', 'context key exists');

-- (c) public.players carries exactly the two expected policies.
select policies_are(
  'public', 'players',
  array['Public players are readable', 'Automation writes players']
);

-- (d) public.players is protected by row-level security, and the private alias
-- table is invisible to the anonymous API role.
select is(
  (select relrowsecurity from pg_class where oid = 'public.players'::regclass),
  true,
  'row-level security is enabled on public.players'
);

select table_privs_are(
  'private', 'member_aliases', 'anon', array[]::text[],
  'anon holds no privileges on private.member_aliases'
);

-- (e) automation_worker holds no DELETE grant on public.players.
select is_empty(
  $$select 1 from information_schema.role_table_grants
     where grantee = 'automation_worker'
       and table_name = 'players'
       and privilege_type = 'DELETE'$$,
  'automation_worker holds no DELETE grant on public.players'
);

-- (f) Two trade_revisions rows sharing a non-null semantic_fingerprint violate the
-- partial unique index.
insert into public.trades (season_id, trade_code)
values ((select id from public.seasons where year = 2026), 'TEST-TRADE-FINGERPRINT');

insert into public.trade_revisions (trade_id, revision, terms, semantic_fingerprint)
values (
  (select id from public.trades where trade_code = 'TEST-TRADE-FINGERPRINT'),
  1,
  '{}'::jsonb,
  'fingerprint-abc'
);

select throws_ok(
  $$insert into public.trade_revisions (trade_id, revision, terms, semantic_fingerprint)
    values (
      (select id from public.trades where trade_code = 'TEST-TRADE-FINGERPRINT'),
      2,
      '{}'::jsonb,
      'fingerprint-abc'
    )$$,
  '23505'::char(5),
  null,
  'duplicate semantic_fingerprint violates the unique index'
);

select * from finish();
rollback;
