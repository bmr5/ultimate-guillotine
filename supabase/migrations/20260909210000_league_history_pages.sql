-- Public history: the analyst's trade catalog and one row of results per season. Same shape
-- as the nine existing public tables, minus any DELETE grant: history is not retracted.

-- Both jsonb columns are validated by a function rather than left open. A jsonb column on an
-- anon-readable table is the one place a sentence out of the league chat could arrive without
-- anybody adding a column for it, so the shapes are closed: an unknown key, an unknown asset
-- kind, or a free-text condition label is refused by the database, not only by the loader.

-- Every shape the trade catalog may publish, and nothing else. The loader
-- (`ultimate_guillotine.history.catalog._clean_asset`) copies these fields through an
-- allowlist; this constraint is the same allowlist restated where it cannot be edited out
-- of a Python file by accident.
create function public.trade_catalog_assets_ok(assets jsonb)
returns boolean
language plpgsql
immutable
parallel safe
set search_path = ''
as $function$
declare
  entry jsonb;
  kind text;
  allowed text[];
  int_fields text[];
  text_fields text[];
begin
  if assets is null or jsonb_typeof(assets) <> 'array' then
    return false;
  end if;

  for entry in select value from jsonb_array_elements(assets) as elements(value) loop
    if jsonb_typeof(entry) <> 'object' then
      return false;
    end if;

    kind := entry ->> 'kind';
    if kind = 'player' then
      allowed := array['kind', 'sleeper_player_id', 'name', 'position', 'from_party', 'to_party'];
      int_fields := array['from_party', 'to_party'];
      text_fields := array['sleeper_player_id', 'name', 'position'];
    elsif kind = 'faab' then
      allowed := array['kind', 'amount', 'from_party', 'to_party'];
      int_fields := array['amount', 'from_party', 'to_party'];
      text_fields := array[]::text[];
    elsif kind = 'condition' then
      allowed := array['kind', 'label', 'week'];
      int_fields := array['week'];
      text_fields := array[]::text[];
      -- A condition is a label from a closed set, never prose.
      if entry ->> 'label' is null
         or entry ->> 'label' not in
              ('rental', 'return_after_week', 'conditional', 'keeper', 'two_way') then
        return false;
      end if;
    else
      return false;
    end if;

    -- No key the shape does not name.
    if exists (select 1 from jsonb_object_keys(entry) as keys(key) where key <> all (allowed)) then
      return false;
    end if;

    -- Whole numbers or null, never a string standing in for one.
    if exists (
      select 1
      from unnest(int_fields) as fields(field)
      where case jsonb_typeof(entry -> field)
              when 'number' then (entry -> field)::numeric <> trunc((entry -> field)::numeric)
              when 'null' then false
              else entry ? field
            end
    ) then
      return false;
    end if;

    -- Short strings or null. 120 characters holds any Sleeper player name and no paragraph.
    if exists (
      select 1
      from unnest(text_fields) as fields(field)
      where case jsonb_typeof(entry -> field)
              when 'string' then length(entry ->> field) > 120
              when 'null' then false
              else entry ? field
            end
    ) then
      return false;
    end if;
  end loop;

  return true;
end;
$function$;

-- One entry per elimination, in the shape `history.records.read_eliminations` builds. `note`
-- is a short caption, capped so it cannot become a transcript.
create function public.season_results_eliminations_ok(eliminations jsonb)
returns boolean
language plpgsql
immutable
parallel safe
set search_path = ''
as $function$
declare
  entry jsonb;
  allowed constant text[] :=
    array['week', 'order', 'member_id', 'gulag_out', 'pool_out', 'remaining', 'note'];
  int_fields constant text[] :=
    array['week', 'order', 'member_id', 'gulag_out', 'pool_out', 'remaining'];
begin
  if eliminations is null or jsonb_typeof(eliminations) <> 'array' then
    return false;
  end if;

  for entry in select value from jsonb_array_elements(eliminations) as elements(value) loop
    if jsonb_typeof(entry) <> 'object' then
      return false;
    end if;

    if exists (select 1 from jsonb_object_keys(entry) as keys(key) where key <> all (allowed)) then
      return false;
    end if;

    if exists (
      select 1
      from unnest(int_fields) as fields(field)
      where case jsonb_typeof(entry -> field)
              when 'number' then (entry -> field)::numeric <> trunc((entry -> field)::numeric)
              when 'null' then false
              else entry ? field
            end
    ) then
      return false;
    end if;

    -- Parenthesised because plpgsql ends an `if` expression at the first `then` it sees.
    if (case jsonb_typeof(entry -> 'note')
          when 'string' then length(entry ->> 'note') > 120
          when 'null' then false
          else entry ? 'note'
        end) then
      return false;
    end if;
  end loop;

  return true;
end;
$function$;

-- Neither table stores a person's name. Parties and champions are public.members ids; a name
-- the loader could not resolve becomes a count, so nothing here can leak a nickname or a
-- workbook cell. `season` is the plain year, not season_id: the catalog reaches back past the
-- seasons the league has rows for. season_id is filled in when a row exists, and a rerun after
-- the backfill fills it in for seasons that gained one.
create table public.trade_catalog (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  catalog_id text not null unique,
  season int not null,
  season_id bigint references public.seasons (id),
  week int,
  occurred_on date,
  trade_type text not null,
  structure text not null,
  party_member_ids bigint[] not null default '{}',
  party_count int not null,
  assets jsonb not null default '[]'
    constraint trade_catalog_assets_shape check (public.trade_catalog_assets_ok(assets)),
  faab_total int,
  confidence text not null check (confidence in ('high', 'medium', 'low')),
  source text not null default 'catalog' check (source in ('catalog', 'registered')),
  unresolved_parties int not null default 0,
  loaded_at timestamptz not null,
  -- A trade the catalog cannot place in time is a trade the pages cannot sort or filter, so
  -- the loader must supply one of the two rather than publish a row that floats.
  constraint trade_catalog_when_known check (week is not null or occurred_on is not null)
);

comment on column public.trade_catalog.assets is
  'Array of assets, each exactly one of three closed shapes and no other key: '
  '{"kind":"player","sleeper_player_id":text,"name":text,"position":text,'
  '"from_party":int,"to_party":int} (name is the Sleeper player name, which is public); '
  '{"kind":"faab","amount":int,"from_party":int,"to_party":int}; '
  '{"kind":"condition","label":one of rental|return_after_week|conditional|keeper|two_way,'
  '"week":int}. Every field is nullable but typed, strings cap at 120 characters, and '
  'anything else is refused by trade_catalog_assets_ok. No chat text, no analyst notes.';

create index trade_catalog_season_idx on public.trade_catalog (season);
create index trade_catalog_trade_type_idx on public.trade_catalog (trade_type);
create index trade_catalog_parties_idx on public.trade_catalog using gin (party_member_ids);

create table public.season_results (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  season int not null unique,
  season_id bigint references public.seasons (id),
  champion_member_id bigint references public.members (id),
  co_champion_member_id bigint references public.members (id),
  runner_up_member_id bigint references public.members (id),
  third_member_id bigint references public.members (id),
  team_count int,
  -- Ordered, one entry per week. Named entries come from the Adjudicator's league_events for
  -- 2026 on; 2023 and 2024 carry the records workbook's counts with member_id null.
  eliminations jsonb not null default '[]'
    constraint season_results_eliminations_shape
    check (public.season_results_eliminations_ok(eliminations)),
  notes text,
  unresolved_names int not null default 0,
  source text not null default 'records-xlsx',
  loaded_at timestamptz not null
);

comment on column public.season_results.eliminations is
  'Array of elimination entries, each with no key but week, order, member_id, gulag_out, '
  'pool_out, remaining (whole numbers or null) and note (a caption of at most 120 '
  'characters, or null). member_id is a public.members id; the workbook-era seasons carry '
  'counts with member_id null. Enforced by season_results_eliminations_ok.';

alter table public.trade_catalog enable row level security;
alter table public.season_results enable row level security;

revoke all on public.trade_catalog from anon, authenticated;
revoke all on public.season_results from anon, authenticated;
grant select on public.trade_catalog to anon, authenticated;
grant select on public.season_results to anon, authenticated;

create policy "Public trade_catalog are readable" on public.trade_catalog for select using (true);
create policy "Public season_results are readable" on public.season_results for select using (true);

create policy "Automation writes trade_catalog" on public.trade_catalog
  for all to automation_worker using (true) with check (true);
create policy "Automation writes season_results" on public.season_results
  for all to automation_worker using (true) with check (true);

grant select, insert, update on public.trade_catalog to automation_worker;
grant select, insert, update on public.season_results to automation_worker;
grant usage, select on all sequences in schema public to automation_worker;
