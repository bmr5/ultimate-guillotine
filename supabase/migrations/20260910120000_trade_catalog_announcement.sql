-- The trade catalog gains the league's own announcement of each trade.
--
-- Ben's ruling (2026-09-10): "include the actual text of the trade to give more context, it is
-- hard to understand these tiles". So this column is chat-derived text published on purpose --
-- the first and only such field on either history table. It does not weaken the rule the rest of
-- `league_history_pages.sql` enforces; it names the one exception to it. The analyst's `notes`
-- are still never loaded, and the loader's allowlist (`history.catalog.CATALOG_FIELDS`) is still
-- the place that decides, so a field the analyst adds next month is still dropped by default.
--
-- Plain `text`, nullable, with no validator: `assets` is closed because it is a shape and a
-- shape can be checked, whereas this is prose and the whole point of it is that it is prose.
-- Null means the record carried no text, which the page renders as nothing rather than as a
-- placeholder. The table's SELECT grants are table-wide, so anon reads the new column with the
-- rest and no grant is restated here.
alter table public.trade_catalog add column announcement text;

comment on column public.trade_catalog.announcement is
  'The league''s own announcement of the trade: the classification record''s source_texts '
  'joined with a blank line between messages, or null when the record carried none. '
  'Published by Ben''s decision of 2026-09-10 -- it is the one chat-derived field these '
  'tables carry. The analyst''s private notes are not loaded here or anywhere.';
