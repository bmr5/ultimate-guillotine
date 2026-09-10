-- TEST- trades are rehearsals: alerts logged from the self-test chat so the bot can be
-- tried without the league seeing anything. The web app reads as anon/authenticated
-- (VITE_SUPABASE_ANON_KEY), so hiding them here hides them from every page at once --
-- the board's trade cards, /trades, /history, the player card -- and from the Realtime
-- feed, which applies the same policies. The automation keeps its own "Automation writes
-- …" policies (automation_worker, using (true)) and still sees them, which is how
-- `ug trades list`, `ug trades rescind` and the video worker keep working on them.
-- Ben (2026-09-10): "filter any test trades out of the web app".

drop policy "Public trades are readable" on public.trades;
create policy "Public trades are readable" on public.trades
  for select using (trade_code not like 'TEST-%');

-- A revision is readable only when its trade is: the subquery runs under the same
-- role, so the trades policy above is what decides.
drop policy "Public trade_revisions are readable" on public.trade_revisions;
create policy "Public trade_revisions are readable" on public.trade_revisions
  for select using (
    trade_id in (select id from public.trades where trade_code not like 'TEST-%')
  );

-- The registrar's trade events carry the code in their payload.
drop policy "Public league_events are readable" on public.league_events;
create policy "Public league_events are readable" on public.league_events
  for select using (coalesce(payload->>'trade_code', '') not like 'TEST-%');
