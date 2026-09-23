# 2026 season archive

The archive records gulag qualification, actual participation, survival, official elimination, and the champion separately. Week 1 sends two teams to the next gulag and eliminates nobody. Weeks 2–11 cut the current gulag loser and select two eligible general-pool teams for the following contest. Week 12 cuts the final gulag loser and one eligible general-pool team. Weeks 13–16 cut the lowest remaining scorer. Week 17 records the champion and runner-up.

Production activation completed September 10, 2026. Both migrations are applied, all four jobs are enabled, and the first capture saved 18 teams. The first weekly checkpoint is September 14 at 11:30 PM Central, followed by September 15 at 8:00 AM verification. The website tab was published September 10 at 7:34 PM Central and verified at https://ultimate-guillotine-sage.vercel.app/current-season. Release dpl_BBewBdvuTnmcsW4evCwN7PwbX7vz was built from committed source f13ca32, without unrelated uncommitted edits. The board loads without the final-roster error.

## Scheduled work

The existing guillotine Hermes profile runs four local-output jobs:

| Job | Schedule, America/Chicago | Purpose |
| --- | --- | --- |
| `guillotine-archive-capture` | Every 2 minutes | Save current rosters, names, FAAB, lineups, and source scores while the 2026 regular season is active |
| `guillotine-archive-retry` | Every 15 minutes | Process due weekly jobs, retry incomplete games, and check corrections |
| `guillotine-week-close` | Monday 11:30 PM | Begin the weekly provisional result |
| `guillotine-week-verify` | Tuesday 8:00 AM | Confirm results after games finish and score inputs stay unchanged for at least 30 minutes |

The jobs use Python and Sleeper reads without LLM calls. After confirmation commits, `archive tick` sends a short cuts and gulag text to the registered production league chat. Capture and provisional results stay silent; archive jobs do not post to Discord. The existing operations run audit can detect missed executions. Reinstall only these four jobs with `.venv/bin/python hermes/guillotine/install_archive.py`. It updates jobs by name and requires a host using Central time in summer and winter. The profile gateway must remain running.

The database stores each week's due time, observed cutoff, candidate hash, and published revision. A process restart does not lose progress. A delayed or reopened game prevents confirmation. After confirmation, corrections are checked hourly for seven days and daily through the end of the season correction window. A correction replaces the whole week's current view, withdraws dependent later weeks, and recalculates official elimination flags. Earlier snapshots remain available as evidence.

## Cuts and gulag announcement

Enabled September 14, 2026; gulag qualifiers added September 15. Tuesday's 8 AM Central confirmation sends the week's cut names, number of teams remaining, and the two qualifiers for the following gulag, with the usual bot signature. Week 1 says `Week 1: Nobody was cut. All 18 teams remain alive.` followed by `Week 2 gulag qualifiers: Nick R and Brandon L.` Gulag qualification is distinct from elimination and does not imply an agreed substitute is already assigned. Week 12 lists both cuts and no next gulag; subsequent weeks also omit that line. Rosters and FAAB are not included.

The announcement requires a production archive, production delivery mode, and contiguous confirmed weeks. Unfinished games or unresolved rulings delay it until a retry confirms the result. The existing 15-minute retry also recovers failed delivery without requiring another score revision. It checks the stored production chat and participant fingerprint before sending.

`archive-cuts` agent runs and outbound message records retain delivery state. A season lock serializes publication and announcements; reservations commit before sending. Normal retries and score-only revisions do not repeat a delivered result. A changed cut list or gulag pair sends a `Correction:` message. The original cuts-only announcement receives one complete correction with the missing gulag names; its original delivery record is preserved. An ambiguous send reuses its original run and text so the delivery layer can reconcile it with message history. Test archives and test/disabled delivery modes never send cut announcements.

## Capture limits

The cutoff is an observation time, not an exact final-whistle timestamp. The first completion observation pins the roster and balance used for that week. A nearby preceding observation is retained if holdings changed during the completion poll. Tuesday verification and later corrections cannot replace that evidence with a cleared roster or a later FAAB balance. Missing capture coverage is labeled partial; an unavailable balance stays unknown.

Gulag entry uses the preceding week's saved roster, with partial coverage, because an exact penalty/reset timestamp is not yet integrated. Explicit keeper selections are not inferred. A substitute's qualifier and beneficiary remain distinct from the actual participant. Registered dollar amounts are not automatically applied to balances.

## Inspect and resolve

Run commands from the repository root. They use the configured production connection; automated tests use a separate local database and rollback every fixture.

```sh
.venv/bin/ug archive status
.venv/bin/ug archive capture
.venv/bin/ug archive tick
```

Missing scores, cutoff ties, invalid identities, incomplete earlier weeks, or accepted protection agreements without a contest assignment produce an unresolved result. They do not invent an official cut. The status command shows each week's exception.

For a substitution or tie, write a commissioner ruling JSON file and run `.venv/bin/ug archive ruling --file /absolute/path/ruling.json`. IDs are stable `public.teams.id` values, not Sleeper roster numbers. For example:

```json
{
  "week": 2,
  "actor": "Commish",
  "reason": "Accepted agreement: the substitute takes the qualifier's place",
  "substitutions": {"101": 103},
  "tie_order": [],
  "reviewed_trade_codes": ["T-2026-001"]
}
```

This example requires replacing the IDs and trade code with the actual records. `week` is the contest week. Substitution keys are original qualifiers; values are actual participants. `tie_order` lists the tied teams from lowest to highest when an explicit ruling decides the boundary. `reviewed_trade_codes` assigns an accepted protection agreement to the reviewed contest even if it was not exercised. A newer ruling replaces that week's complete ruling, so include all its applicable decisions. An amended or rescinded reviewed agreement requires a refreshed ruling. The command records the actor, reason, and accepted trade revision, then makes the week due for another check. It never edits Sleeper or sends a message.

## Deployment and verification

Apply `20260911010000_season_event_archive.sql` and `20260911011000_archive_automation.sql`, then enable with `.venv/bin/ug archive enable --season 2026 --scope production`. Scope cannot be switched on an existing archive. Enabling checks the 18-team league identity and all 17 scheduled scoring weeks. The website route is `/current-season`; it reads only production revisions. The board reads corrected cut rosters through `effective_final_rosters`.

The 2026 rules are the only rules enabled by this implementation. Review the next season's rules and identity mapping before extending activation beyond 2026. No pre-2026 history is reconstructed. General chat queries and player career-history aggregation remain separate follow-up work.

## Website release checks

For a local Vercel production build, verify that both `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` are nonempty after `vercel pull`. These are public browser settings. The key is the Supabase publishable key, never a privileged service-role key or database credential. Vercel had marked these values sensitive, so the CLI exported blank values and the first local release failed to start. The previous site was restored, the two public settings were made available to builds, and the corrected release was verified before promotion.

The release passed its production build, lint, and 965 web tests. The isolated test run needed placeholder public environment values for the player-card suite. Browser verification confirmed the history empty state and live board data. The automatic jobs remained active throughout the website release.

## Current season navigation

The active season archive now has its own **Current season** tab in the main navigation, next to Board. **History** contains only past-season champion cards. Old `/history/2026` URLs redirect to `/current-season`, preserving the query string and selected week. The header wraps its links on small screens.

Release `dpl_5s9Dh8Wsu72oGYM4k8oyuR8jBzGd` publishes this navigation change. Sixteen existing page/layout tests pass, along with lint and the production build. Browser checks cover the Week 12 redirect, the separate past-season view, and navigation at a 390-pixel viewport.
