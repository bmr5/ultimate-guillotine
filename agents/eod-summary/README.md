# EOD Summary

Design: `docs/superpowers/specs/2026-09-10-eod-summary-agent-design.md`. Runbook:
`docs/runbooks/mac-mini.md`, section 11.

## Purpose and owner

One HTML post to the league chat on four days a week: the gulag pair when active,
every general-pool team's score, projected finish and Monte Carlo odds in one table,
and the roster problems worth fixing. Owner: the commissioner, through
`#guillotine-drafts` and the run history.
In gulag weeks, the two competitors appear in their own head-to-head section;
the ranked pool table contains only the other live teams.

## Inputs

Public league data only, all from Supabase through the data layer: rosters, lineup slots,
this week's projections and coverage, FAAB, elimination, the week's scores and every earlier
week's, the players directory (NFL team and injury flag), the Adjudicator's `gulag_entry`
events when they exist, and executed transactions retained in the internal snapshot
but omitted from the report. One network read outside the
data layer: Sleeper's public NFL schedule, for which games are over.

No private member data is read. The model, when used, is handed the rendered sections of the
message and nothing else.

## Outputs and retention

- `public.survival_snapshots` — one row per run with the odds per team, the model version,
  the simulation count and the input hash. Kept forever; public and anon-readable.
- `public.recaps` — one row per composed message, `recap_kind = eod:<local date>`, `draft`
  until delivery succeeds, then `sent`. Kept forever.
- The post, through the delivery layer, to the chat the delivery mode names: one
  self-contained HTML file (`MonteCarlo-<date>.html`)
  that Quick Look opens on a phone. A preview of the text in `#guillotine-drafts` in every mode
  but production.

## External tools and permissions

- The Sleeper schedule feed (read-only, public).
- The scheduled report runs with `--no-ai`. It has no generated headline or blurb.
- The delivery layer, for the send. The agent has no other write path.

## Schedule and failure behaviour

`guillotine-eod-summary` at `15 8 * * 0,1` and `guillotine-eod-summary-waivers` at
`0 12 * * 4,6`, Mac mini local time (8:15 AM Sunday and Monday; noon Thursday
and Saturday after each waiver round; Tuesday, Wednesday and Friday off), both agent `eod-summary`, one
status line to `#guillotine-ops`, gap budget 3000 minutes. The league sees it as the Guillotine Daily. Off-season and post-final weeks are a
no-op. If the schedule, scores or projections cannot support odds, the job reports the
reason to ops and sends nothing. A report already posted that day is
left alone; `--force` overrides for rehearsal. Full table in the design.

## Dry run and review

```bash
uv run --project packages/league-automation ug summary eod --fixture --no-ai   # no database
uv run --project packages/league-automation ug summary eod --dry-run --out /tmp  # the real league; writes the HTML there
uv run --project packages/league-automation ug summary eod --json              # the fact packet
```

None of these writes, sends, or records a run. Review the scheduled run in
`#guillotine-drafts` (the preview), `#guillotine-feed` (the mirror of what was sent), and
`public.recaps`.
