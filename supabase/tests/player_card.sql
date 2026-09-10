-- The player card's three tables: the auction, the executed transaction log, and the
-- per-player index over it. Spec: docs/superpowers/specs/2026-09-10-player-card-design.md.
--
-- One file for the three because they land in one migration and share one shape: RLS on,
-- readable by the anon key, written by automation_worker with no delete grant, and none of
-- them published to Realtime — the mark depends on roster_holdings, which already streams,
-- and the card fetches on open.
begin;
select plan(19);

-- `supabase db reset` seeds only public.seasons; the row-level assertions need a team.
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

select has_table('public', 'draft_picks', 'draft_picks table exists');
select has_table('public', 'transactions', 'transactions table exists');
select has_table('public', 'transaction_moves', 'transaction_moves table exists');

select is(
  (select relrowsecurity from pg_class where oid = 'public.draft_picks'::regclass),
  true, 'draft_picks has row level security enabled'
);
select is(
  (select relrowsecurity from pg_class where oid = 'public.transactions'::regclass),
  true, 'transactions has row level security enabled'
);
select is(
  (select relrowsecurity from pg_class where oid = 'public.transaction_moves'::regclass),
  true, 'transaction_moves has row level security enabled'
);

select policies_are(
  'public', 'draft_picks',
  array['Public draft_picks are readable', 'Automation writes draft_picks']
);
select policies_are(
  'public', 'transactions',
  array['Public transactions are readable', 'Automation writes transactions']
);
select policies_are(
  'public', 'transaction_moves',
  array['Public transaction_moves are readable', 'Automation writes transaction_moves']
);

-- No DELETE on any of the three: none of them is a cache, and roster_holdings stays the one
-- public table the worker may delete from.
select table_privs_are(
  'public', 'draft_picks', 'automation_worker', array['SELECT', 'INSERT', 'UPDATE'],
  'automation_worker holds SELECT, INSERT and UPDATE on public.draft_picks and nothing else'
);
select table_privs_are(
  'public', 'transactions', 'automation_worker', array['SELECT', 'INSERT', 'UPDATE'],
  'automation_worker holds SELECT, INSERT and UPDATE on public.transactions and nothing else'
);
select table_privs_are(
  'public', 'transaction_moves', 'automation_worker', array['SELECT', 'INSERT', 'UPDATE'],
  'automation_worker holds SELECT, INSERT and UPDATE on public.transaction_moves and nothing else'
);

-- The natural keys the syncs upsert on.
select col_is_unique(
  'public', 'draft_picks', array['season_id', 'sleeper_player_id'],
  'a player is drafted once per season'
);
select col_is_unique(
  'public', 'draft_picks', array['season_id', 'sleeper_draft_id', 'pick_no'],
  'a pick number is used once per draft'
);
select col_is_unique(
  'public', 'transactions', array['sleeper_transaction_id'],
  'one row per Sleeper transaction'
);
select col_is_unique(
  'public', 'transaction_moves', array['transaction_id', 'sleeper_player_id', 'action'],
  'one move per player per side of a transaction'
);

-- An auction pick without a price is a malformed payload, not a free player.
select throws_ok(
  $$insert into public.draft_picks
      (season_id, team_id, sleeper_player_id, sleeper_draft_id, pick_no, round, draft_slot,
       amount, drafted_at, synced_at)
    values ((select id from public.seasons where year = 2026),
            (select id from public.teams where sleeper_roster_id = 999),
            'pgtap-player', 'pgtap-draft', 1, 1, 1, 0, now(), now())$$,
  '23514', null, 'draft_picks refuses an amount below 1'
);

-- A transaction is one of four kinds; a fifth is skipped by the sync, never stored.
select throws_ok(
  $$insert into public.transactions
      (season_id, sleeper_transaction_id, kind, week, occurred_at, raw, synced_at)
    values ((select id from public.seasons where year = 2026),
            'pgtap-tx', 'gift', 1, now(), '{}', now())$$,
  '23514', null, 'transactions refuses an unknown kind'
);

-- None of the three is published: the card fetches on open, the mark rides on roster_holdings.
select is(
  (select count(*)::int from pg_publication_tables
     where pubname = 'supabase_realtime' and schemaname = 'public'
       and tablename in ('draft_picks', 'transactions', 'transaction_moves')),
  0, 'the player card tables are not published to supabase_realtime'
);

select * from finish();
rollback;
