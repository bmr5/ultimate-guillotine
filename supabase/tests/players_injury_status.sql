begin;
select plan(5);

-- Ben's addendum: an injured starter with no projection was reading as missing data. The
-- board can only tell the two apart if the directory carries Sleeper's own injury flag.
select has_column(
  'public', 'players', 'injury_status',
  'players carries the Sleeper injury status'
);

-- Nullable, because the overwhelming majority of the feed carries no status at all
-- (11,496 of 12,227 players on 2026-09-09) and an absent flag is not an injury.
select col_is_null(
  'public', 'players', 'injury_status',
  'injury_status is nullable: most of the feed has no flag'
);

select lives_ok(
  $$insert into public.players
      (sleeper_player_id, full_name, position, team, active, injury_status, synced_at)
    values ('pgtap-injury-ir', 'pgTAP Injured', 'TE', 'KC', true, 'IR', now())$$,
  'a status Sleeper actually reports is accepted'
);

-- A tenth Sleeper status must not break the sync. The vocabulary is enforced in
-- `sleeper/players.py` (`KNOWN_INJURY_STATUSES`), which reads an unknown value as no flag
-- and counts it into the run's report; the column itself takes whatever it is given, so a
-- value nobody has seen before can never freeze the whole directory on the last good rows.
select lives_ok(
  $$insert into public.players
      (sleeper_player_id, full_name, position, team, active, injury_status, synced_at)
    values ('pgtap-injury-new', 'pgTAP Novel', 'TE', 'KC', true, 'Sprained ankle', now())$$,
  'a status this build has never seen is stored rather than refused'
);

-- And the vocabulary is still written down where a reader of the schema will find it.
select matches(
  (select col_description('public.players'::regclass, attnum)
     from pg_attribute
    where attrelid = 'public.players'::regclass and attname = 'injury_status'),
  'Questionable, Doubtful, Out, IR, PUP, Sus, NA, COV, DNR',
  'the column comment records the statuses Sleeper emits'
);

select * from finish();
rollback;
