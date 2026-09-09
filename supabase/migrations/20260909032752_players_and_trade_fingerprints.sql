create table public.players (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  sleeper_player_id text not null unique,
  full_name text not null,
  first_name text,
  last_name text,
  position text,
  team text,
  active boolean not null default true,
  synced_at timestamptz not null
);
create index players_full_name_idx on public.players (lower(full_name));

alter table public.players enable row level security;
revoke all on public.players from anon, authenticated;
grant select on public.players to anon, authenticated;
create policy "Public players are readable" on public.players for select using (true);
create policy "Automation writes players" on public.players
  for all to automation_worker using (true) with check (true);
grant select, insert, update on public.players to automation_worker;
grant usage, select on all sequences in schema public to automation_worker;

create table private.member_aliases (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  member_id bigint not null references public.members (id),
  alias text not null,
  alias_normalized text not null unique
);
create index member_aliases_member_id_idx on private.member_aliases (member_id);
revoke all on private.member_aliases from public, anon, authenticated;
grant select, insert, update, delete on private.member_aliases to automation_worker;

alter table public.trade_revisions add column semantic_fingerprint text;
create unique index trade_revisions_semantic_fingerprint_key
  on public.trade_revisions (semantic_fingerprint) where semantic_fingerprint is not null;
alter table public.trades add column context_key text;
create index trades_context_key_idx on public.trades (context_key);
