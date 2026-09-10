-- The League Agent: one Hermes session per conversation thread, the run that
-- resumed it, and a private record of every question and answer.
--
-- Everything here is private: revoked from anon/authenticated like the rest of
-- the schema, readable through the worker role and the dashboard only. The
-- question is stored verbatim, as private.source_messages.excerpt already is,
-- because the record is for the commissioner's review and nothing on the site
-- reads it.

create table private.agent_sessions (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  hermes_session_id text not null unique,
  chat_guid_hash text not null,
  last_used_at timestamptz not null default now(),
  turns int not null default 1
);

alter table private.agent_runs
  add column session_id bigint references private.agent_sessions (id);

-- A follow-up is resolved from the reply's thread GUID to the bot's outbound
-- message, so the lookup by GUID has to be indexed: it runs under the listener
-- lock for every inline reply the chat produces.
create index outbound_messages_bluebubbles_guid_idx
  on private.outbound_messages (bluebubbles_guid);

create table private.agent_answers (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  run_id bigint not null references private.agent_runs (id),
  session_id bigint references private.agent_sessions (id),
  chat_guid_hash text not null,
  asker_member_id bigint references public.members (id),
  question text not null,
  is_follow_up boolean not null default false,
  kind text not null check (kind in ('answer', 'clarification', 'refusal')),
  chat_text text not null,
  source_line text not null default '',
  report_title text,
  report_html text,
  facts jsonb not null default '{}',
  sources jsonb not null default '[]',
  prompt_version text not null,
  model text not null
);

create index agent_answers_created_at_idx on private.agent_answers (created_at desc);

revoke all on private.agent_sessions, private.agent_answers from public, anon, authenticated;
revoke all on all sequences in schema private from public, anon, authenticated;
grant select, insert, update on private.agent_sessions, private.agent_answers to automation_worker;
grant usage, select on all sequences in schema private to automation_worker;
