-- Private operational schema: automation-internal tables used by the league
-- automation agents (message ingestion, outbound delivery, projections,
-- knowledge sources, heartbeats/expected-run monitoring) plus the
-- least-privilege `automation_worker` role that operates on them.
--
-- The private schema is never exposed via PostgREST (see supabase/config.toml
-- api.schemas) and is fully revoked from public/anon/authenticated: only the
-- automation_worker role (and superuser/owner roles) may touch it.

create schema private;

revoke all on schema private from public, anon, authenticated;

create table private.member_contacts (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  member_id bigint not null references public.members (id),
  handle_hash text not null unique,
  alias text
);

create index member_contacts_member_id_idx on private.member_contacts (member_id);

create table private.delivery_targets (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  mode text not null unique check (mode in ('test', 'production')),
  chat_guid text not null,
  chat_guid_hash text not null,
  participant_fingerprint text,
  label text not null
);

create table private.source_messages (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  source_guid text not null unique,
  chat_guid_hash text not null,
  sender_hash text,
  direction text not null check (direction in ('inbound', 'outbound')),
  sent_at timestamptz not null,
  content_fingerprint text not null,
  excerpt text,
  trigger_name text,
  unique (chat_guid_hash, content_fingerprint, sent_at)
);

create index source_messages_chat_guid_hash_sent_at_idx
  on private.source_messages (chat_guid_hash, sent_at desc);

create table private.webhook_receipts (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  event_id text not null unique,
  received_at timestamptz not null default now(),
  outcome text not null
);

create table private.agent_runs (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  agent text not null,
  trigger text not null,
  idempotency_key text not null unique,
  input_version text,
  status text not null default 'running'
    check (status in ('running', 'succeeded', 'failed', 'duplicate')),
  attempts int not null default 1,
  output_hash text,
  error text,
  invoked_by text,
  started_at timestamptz not null default now(),
  finished_at timestamptz
);

create index agent_runs_agent_started_at_idx on private.agent_runs (agent, started_at desc);

create table private.outbound_messages (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  run_id bigint references private.agent_runs (id),
  delivery_target_id bigint not null references private.delivery_targets (id),
  content text not null,
  content_hash text not null,
  state text not null default 'reserved'
    check (state in ('reserved', 'sending', 'sent', 'reconciled', 'failed')),
  reserved_at timestamptz not null default now(),
  sent_at timestamptz,
  bluebubbles_guid text,
  error text,
  unique (delivery_target_id, content_hash, reserved_at)
);

create index outbound_messages_run_id_idx on private.outbound_messages (run_id);
create index outbound_messages_delivery_target_id_idx
  on private.outbound_messages (delivery_target_id);
create index outbound_messages_delivery_target_id_state_idx
  on private.outbound_messages (delivery_target_id, state);

create table private.projection_snapshots (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season_id bigint not null references public.seasons (id),
  week int not null,
  source text not null,
  source_at timestamptz not null,
  coverage numeric(5, 4) not null,
  payload jsonb not null
);

create index projection_snapshots_season_id_idx on private.projection_snapshots (season_id);

create table private.knowledge_sources (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  source_key text not null unique,
  version text not null,
  path text not null,
  sha256 text not null
);

create table private.heartbeats (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  component text not null unique,
  beat_at timestamptz not null default now()
);

create table private.expected_runs (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  job_name text not null unique,
  agent text not null,
  max_gap_minutes int not null,
  schedule text not null
);

-- Supabase's default privileges grant all table privileges to anon/authenticated
-- on creation in exposed schemas; the private schema is not exposed via
-- PostgREST, but revoke explicitly anyway so nothing is left to chance.
revoke all on all tables in schema private from public, anon, authenticated;
revoke all on all sequences in schema private from public, anon, authenticated;

-- Least-privilege automation role: no login (assumed via a separate login
-- role, see scripts/configure_worker_role.sql.example), no DELETE anywhere,
-- and no ability to touch schemas other than the nine public league tables
-- and the private automation tables.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'automation_worker') then
    create role automation_worker nologin;
  end if;
end $$;

grant usage on schema private to automation_worker;
grant select, insert, update on all tables in schema private to automation_worker;
grant usage, select on all sequences in schema private to automation_worker;
alter default privileges in schema private grant select, insert, update on tables to automation_worker;
alter default privileges in schema private grant usage, select on sequences to automation_worker;

grant select, insert, update on public.seasons, public.members, public.teams,
  public.weekly_results, public.league_events, public.trades,
  public.trade_revisions, public.survival_snapshots, public.recaps
  to automation_worker;
grant usage, select on all sequences in schema public to automation_worker;
