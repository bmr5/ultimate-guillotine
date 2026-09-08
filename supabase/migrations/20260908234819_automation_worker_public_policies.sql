-- The nine public league tables have row level security enabled with SELECT-only
-- policies for the website. RLS applies to every non-superuser, non-owner role, so
-- the INSERT/UPDATE grants the automation_worker role holds are not enough on their
-- own: without a permissive policy, worker inserts fail with InsufficientPrivilege
-- and worker updates silently match zero rows.
--
-- Give automation_worker a full-command permissive policy on each table. The role
-- still holds no DELETE grant on any public table, so "for all" cannot become a
-- delete path: the grant, not the policy, is what bounds the commands available.

create policy "Automation writes seasons" on public.seasons
  for all to automation_worker using (true) with check (true);
create policy "Automation writes members" on public.members
  for all to automation_worker using (true) with check (true);
create policy "Automation writes teams" on public.teams
  for all to automation_worker using (true) with check (true);
create policy "Automation writes weekly_results" on public.weekly_results
  for all to automation_worker using (true) with check (true);
create policy "Automation writes league_events" on public.league_events
  for all to automation_worker using (true) with check (true);
create policy "Automation writes trades" on public.trades
  for all to automation_worker using (true) with check (true);
create policy "Automation writes trade_revisions" on public.trade_revisions
  for all to automation_worker using (true) with check (true);
create policy "Automation writes survival_snapshots" on public.survival_snapshots
  for all to automation_worker using (true) with check (true);
create policy "Automation writes recaps" on public.recaps
  for all to automation_worker using (true) with check (true);
