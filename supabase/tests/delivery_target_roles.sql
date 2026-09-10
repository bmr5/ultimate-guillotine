begin;
select plan(6);

-- (a) The role column exists and defaults to the behaviour every existing row had.
select has_column('private', 'delivery_targets', 'role', 'delivery_targets carries a role');
select col_default_is(
  'private', 'delivery_targets', 'role', 'deliver',
  'a target with no role stated is a delivery target, as every row was before'
);

-- (b) A listen row carries no mode: it is not any mode's destination, and several
-- of them have to coexist. Two of them, in fact -- the unique constraint on `mode`
-- would have refused the second if listen rows carried one.
select lives_ok(
  $$insert into private.delivery_targets (mode, chat_guid, chat_guid_hash, label, role)
    values (null, 'guid-a', 'hash-a', 'a chat', 'listen'),
           (null, 'guid-b', 'hash-b', 'another chat', 'listen')$$,
  'two listen targets coexist, because neither claims a mode'
);

-- (c) The same chat cannot be registered to listen twice: re-registering has to
-- update in place rather than accumulate rows for one conversation.
select throws_ok(
  $$insert into private.delivery_targets (mode, chat_guid, chat_guid_hash, label, role)
    values (null, 'guid-a-again', 'hash-a', 'the same chat', 'listen')$$,
  '23505',
  null,
  'the same chat cannot be registered to listen twice'
);

-- (d) The two columns are tied together in both directions: a listen row that
-- claims a mode, and a delivery target that has lost one, are both unwritable.
select throws_ok(
  $$insert into private.delivery_targets (mode, chat_guid, chat_guid_hash, label, role)
    values ('test', 'guid-c', 'hash-c', 'a chat', 'listen')$$,
  '23514',
  null,
  'a listen target may not claim a delivery mode'
);

select throws_ok(
  $$insert into private.delivery_targets (mode, chat_guid, chat_guid_hash, label, role)
    values (null, 'guid-d', 'hash-d', 'a chat', 'deliver')$$,
  '23514',
  null,
  'a delivery target must name the mode it delivers for'
);

select * from finish();
rollback;
