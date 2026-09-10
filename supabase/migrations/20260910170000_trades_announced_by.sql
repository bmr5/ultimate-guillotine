-- Who posted the announcement. Ben (2026-09-10): "write the announcer of the
-- trade too." A member id, never a handle: the sender is placed by the hashed
-- handle in private.member_contacts and only the public member id is kept.
alter table public.trades add column if not exists announced_by bigint references public.members (id);
comment on column public.trades.announced_by is
  'The member who posted the announcement, when the sender could be placed; null otherwise.';

-- Backfill from the source messages the current revisions point at.
update public.trades t
set announced_by = c.member_id
from public.trade_revisions r
join private.source_messages sm on sm.source_guid = r.terms ->> 'source_message_guid'
join private.member_contacts c on c.handle_hash = sm.sender_hash
where r.id = t.current_revision_id and t.announced_by is null;
