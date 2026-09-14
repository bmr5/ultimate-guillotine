-- Append-only forecast evidence. Existing grants and RLS remain unchanged.
alter table public.survival_snapshots add column if not exists inputs jsonb;
comment on column public.survival_snapshots.inputs is
 'Versioned full forecast input: lineup, actuals, projections, game fractions, phase, parameters and seed. Null for legacy forecasts.';
create index if not exists survival_snapshots_model_week_time
 on public.survival_snapshots (season_id, week, model_version, snapshot_at);
