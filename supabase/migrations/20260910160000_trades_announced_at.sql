-- When the trade was announced in the chat, as opposed to when the registrar
-- logged it. Ben (2026-09-10): "the trade log is a little incorrect because it
-- pulls from the time of scrape and not the actual time of the trade message."
alter table public.trades add column if not exists announced_at timestamptz;
comment on column public.trades.announced_at is
  'When the announcement was posted in the chat (the source message''s sent_at); null for rows logged before this column existed and never matched to a source.';

-- Backfill from the source messages the existing revisions point at.
update public.trades t
set announced_at = sm.sent_at
from public.trade_revisions r
join private.source_messages sm on sm.source_guid = r.terms ->> 'source_message_guid'
where r.id = t.current_revision_id and t.announced_at is null;
