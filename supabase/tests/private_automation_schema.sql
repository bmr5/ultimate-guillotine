begin;
select plan(9);

-- (a) The private schema and its automation-critical tables exist.
select has_schema('private', 'private schema exists');
select has_table('private', 'agent_runs', 'private.agent_runs table exists');
select has_table('private', 'outbound_messages', 'private.outbound_messages table exists');
select has_table('private', 'webhook_receipts', 'private.webhook_receipts table exists');

-- (b) The least-privilege automation role exists.
select has_role('automation_worker', 'automation_worker role exists');

-- (c) anon holds no grants at all on the private schema.
select is_empty(
  $$select 1 from information_schema.role_table_grants
     where grantee = 'anon' and table_schema = 'private'$$,
  'anon holds no grants on private tables'
);

-- (d) automation_worker never holds DELETE, in private or in public, except
-- on private.expected_runs and private.member_aliases: those tables are
-- installer-managed configuration, not league facts, so the worker login may
-- replace their contents.
select is_empty(
  $$select 1 from information_schema.role_table_grants
     where grantee = 'automation_worker'
       and table_schema in ('private', 'public')
       and privilege_type = 'DELETE'
       and not (table_schema = 'private'
                and table_name in ('expected_runs', 'member_aliases'))$$,
  'automation_worker holds no DELETE grant in private or public, aside from '
  'expected_runs and member_aliases'
);

-- (d2) automation_worker does hold DELETE on private.expected_runs.
select isnt_empty(
  $$select 1 from information_schema.role_table_grants
     where grantee = 'automation_worker'
       and table_schema = 'private'
       and table_name = 'expected_runs'
       and privilege_type = 'DELETE'$$,
  'automation_worker holds a DELETE grant on private.expected_runs'
);

-- (e) No queue/scheduler extension is installed.
select is_empty(
  $$select 1 from pg_extension where extname in ('pg_cron', 'pgmq')$$,
  'no pg_cron or pgmq extension is installed'
);

select * from finish();
rollback;
