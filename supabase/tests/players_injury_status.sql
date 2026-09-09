begin;
select plan(4);

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

-- The constraint is the contract with the sync: the only strings that reach this column
-- are the nine the players feed emits. A free-text injury note landing here would show up
-- on a card as an unreadable tag, so it is refused at the door.
select throws_ok(
  $$insert into public.players
      (sleeper_player_id, full_name, position, team, active, injury_status, synced_at)
    values ('pgtap-injury-bad', 'pgTAP Sprained', 'TE', 'KC', true, 'Sprained ankle', now())$$,
  '23514'::char(5),
  null,
  'a status outside Sleeper''s own values violates the check constraint'
);

select * from finish();
rollback;
