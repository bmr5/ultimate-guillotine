# EOD Summary

Design: `docs/superpowers/specs/2026-09-10-eod-summary-agent-design.md`. Runbook:
`docs/runbooks/mac-mini.md`, section 11.

## Purpose and owner

One signed post to the league chat on five mornings a week: every live team's
score and projected finish, the two teams on the block (or the gulag pair), a Monte Carlo
estimate of each team's odds of the week's adverse event, the roster problems worth fixing,
and the moves since the previous post. Owner: the commissioner, through `#guillotine-drafts`
and the run history.

## Inputs

Public league data only, all from Supabase through the data layer: rosters, lineup slots,
this week's projections and coverage, FAAB, elimination, the week's scores and every earlier
week's, the players directory (NFL team and injury flag), the Adjudicator's `gulag_entry`
events when they exist, and tonight's executed transactions. One network read outside the
data layer: Sleeper's public NFL schedule, for which games are over.

No private member data is read. The model, when used, is handed the rendered sections of the
message and nothing else.

## Outputs and retention

- `public.survival_snapshots` — one row per run with the odds per team, the model version,
  the simulation count and the input hash. Kept forever; public and anon-readable.
- `public.recaps` — one row per composed message, `recap_kind = eod:<local date>`, `draft`
  until delivery succeeds, then `sent`. Kept forever.
- The post, through the delivery layer, to the chat the delivery mode names: a short signed
  text, then the summary as one self-contained HTML file (`guillotine-eod-week-<N>-<date>.html`)
  that Quick Look opens on a phone. A preview of the text in `#guillotine-drafts` in every mode
  but production.

## External tools and permissions

- The Sleeper schedule feed (read-only, public).
- The Hermes CLI on the `guillotine` profile, for one structured call (`agents/eod-summary/prompt.md`,
  version `2026.1`) that writes a headline and a blurb. The call is optional: a missing CLI,
  an outage, or a rejected answer means a message without colour, never a failed run.
- The delivery layer, for the send. The agent has no other write path.

## Schedule and failure behaviour

`guillotine-eod-summary` at `15 8 * * 0,1,3` and `guillotine-eod-summary-waivers` at
`15 11 * * 4,6`, Mac mini local time (8:15 AM Wednesday, Sunday and Monday; 11:15 AM Thursday
and Saturday after each waiver round; Tuesday and Friday off -- Ben's cadence), both agent `eod-summary`, one
status line to `#guillotine-ops`, gap budget 3000 minutes. The league sees it as the Guillotine Daily. Off-season and post-final weeks are a
no-op. A schedule outage or projection coverage under 95 percent of the starters still to
play posts a factual message with no percentages and says why. A night already posted is
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
