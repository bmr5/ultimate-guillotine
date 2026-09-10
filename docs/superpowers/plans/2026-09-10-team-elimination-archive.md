# Team elimination archive and player history

Status: the 2026 history tab, private roster capture, deterministic adjudication, correction handling, and four scheduled job definitions are implemented. Both database migrations and all four Hermes jobs are live as of September 10, 2026. The first production capture saved all 18 teams. The website code is built and browser-verified locally; it has not been published by this task. See the [operating runbook](../../runbooks/season-archive.md) for the implemented behavior and its limits. The design below also includes later player-history and general-query work that is not part of this rollout.

## Implemented website view

Ben requested a tab for the 2026 gulag and elimination visualization. The site now has **History → 2026 season** at `/history/2026`, alongside the existing past-champion cards. A selectable 17-week timeline distinguishes the scheduled survival path from confirmed outcomes. Week selection is shareable through `?week=1`. Gulag and cut filters keep qualification, actual entry, survival, official cuts, and the championship distinct. Event cards expand to show their saved roster, lineup roles, score, opponent, money and its observation time, roster cutoff, coverage, and paid-substitution labels.

Empty weeks show "Awaiting results." Unavailable reads show an error with a retry rather than an empty history. Provisional and unresolved records never contribute to confirmed totals. Missing balances remain unknown. No pre-2026 records or current roster holdings feed this page.

Migration `20260911010000_season_event_archive.sql` adds `season_history_weeks`, `team_event_snapshots`, and `team_event_players`, with three public read views. `season_history_weeks` stores complete weekly publication revisions and explicit production/test scope. The current views choose the latest production revision before applying retraction status and join only that revision's events and players. Corrections publish the entire weekly bundle atomically. Migration `20260911011000_archive_automation.sql` adds private observations, durable weekly jobs, explicit commissioner rulings, correction labels, and the corrected final-roster view.

The publisher inserts each complete week revision atomically and updates official elimination flags only from contiguous confirmed weeks. Accepted substitutions and ties require explicit commissioner rulings. Old snapshots remain immutable. Public readers cannot write and cannot see test observations or test outcomes.

Validation passed with 963 web tests, 1,717 Python tests, and 12 database policy/constraint checks. The build and lint pass. Browser access was restored by removing this conversation's explicitly approved local-origin denial; the page can now be verified in the browser.


## Outcome

Preserve the team that existed when a manager entered the gulag or was cut: roster, starting lineup, money, scores, and the ruling that caused the event. Later drops, trades, renames, and stat corrections must not silently change that history.

The board and the planned general league-question agent should answer:

- Who was cut in a given week, and why?
- What was their final roster, who started, and how many points did each starter score?
- How much money did they have left?
- How many eliminated teams was Bijan on at the time they were cut?
- Which players have appeared on the most eliminated teams?
- What happened to those players after the team was cut?

The archive starts with the 2026 season and continues forward each year. Ben confirmed that pre-2026 cut-time data is lost; historical backfill and reconstruction of those seasons are out of scope. Cross-season totals must say “since 2026,” not imply coverage of the league's entire history. This plan does not implement the previously discussed image-request feature or a new general-purpose chatbot.

## Initial audit, before implementation

Read-only audit on September 10, 2026:

| Component | Current behavior | Gap |
| --- | --- | --- |
| `sleeper/roster_state.py` and `sleeper/sync.py` | Maintain current holdings, FAAB, and elimination status; freeze `final_rosters` once | Freeze occurs on first observation, potentially after roster clearing; only roster fields are frozen |
| `team_season_state` | Current budget, usage, record, cumulative points, elimination week/source | Money and record continue updating after elimination |
| `team_week_scores` and `sleeper/scores.py` | Weekly scores, starters and reported player points | Upserts replace observations; full matchup `players` and original score inputs are not preserved by this model |
| `transactions` and `transaction_moves` | Draft-adjacent player movement and FAAB transfers from Sleeper | Current upserts do not retain every source revision; transaction history alone may miss manual money adjustments |
| `apps/web/src/player/derive/journey.ts` | Draft, trade, add/drop, and commissioner movements | No gulag or cut entries |
| Weekly Adjudicator and League Agent designs | Describe authoritative outcomes and question-answer tools | Neither implementation is present in the inspected source tree |

The current database has 18 active 2026 team states, no recorded eliminations, no frozen final rosters, and no finalized `weekly_results`. Existing `league_events` are trades. Existing pre-2026 season summaries remain separate from this new archive and do not contribute to its counts.

## Definitions to make explicit

**Gulag entry is not elimination.** The league rules describe a roster reset with two keepers before the gulag contest. Preserve the roster before that reset separately from the roster that later loses the gulag. A surviving team can enter the gulag again, so every entry is its own event.

### 2026 league transitions

Source: [original league rules](../../rules/ultimate-guillotine-gulag-league-rules.docx), including its season simulation, and the [Weekly Adjudicator design](../specs/2026-08-27-weekly-adjudicator-agent-design.md). Ben explicitly reconfirmed Week 1 on September 10. Encode these rules once in the adjudicator and have the archive consume its events.

| Scoring week completed | Official cuts | Gulag outcome and next contest | Teams still alive after the week |
| --- | --- | --- | --- |
| 1 | None | Bottom two eligible teams qualify for the Week 2 gulag | 18 |
| 2 through 11 | One: loser of that week's gulag contest | Winner returns to the general pool; bottom two eligible general-pool teams qualify for the following week's gulag | 17 after Week 2, decreasing to 8 after Week 11 |
| 12 | Two distinct teams: current gulag loser and lowest eligible general-pool scorer | Resolve the last gulag, with no new entrants | 6 |
| 13 through 16 | One each week: lowest remaining scorer | No gulag | 5, 4, 3, then 2 |
| 17 | Championship runner-up | Record champion and runner-up explicitly | 1 champion |

The rules' table calls the Week 2 victim the "Week 1 Gulag loser" and the Week 12 victim the "Week 11 Gulag loser." Store `qualification_week` and `contest_week` separately: those descriptions refer to the prior week's qualification, not to a second elimination of an already resolved contest. A contest has a stable ID linking its qualification, accepted substitutions, actual participants, and result.

For example, when Week 1 closes, teams A and B qualify for the Week 2 contest. Record both pre-reset rosters and balances, but set neither team's `is_eliminated` flag. After Week 2, A might lose with its rebuilt roster and be officially cut, while B survives. A player on A's Week 1 roster but absent from A's Week 2 cut roster has a gulag-qualification appearance and zero cut appearances from that sequence.

Keep these facts separate:

- `gulag_qualified`: original team selected by the weekly scores, with qualification week and pre-reset snapshot.
- `gulag_entered`: actual participant in the named contest after accepted substitutions, with the roster before its penalty. Without a substitution, this is the original qualifier. Link both events so one ordinary entry does not count twice.
- `gulag_survived`: contest winner returning with its rebuilt roster.
- `eliminated`: terminal cut with a reason of `gulag_loss`, `direct_cut`, or `championship_loss`, and a cut-time snapshot.
- `champion`: the season winner, who is never marked eliminated.

Derive current state from finalized events as general pool, gulag, eliminated, or champion. Qualification for a future contest must not rewrite membership for a contest already in progress. Only a terminal elimination event changes `is_eliminated`, sets the elimination week, or feeds default player cut counts. Championship losses remain distinguishable from earlier cuts in queries and presentation.

The adjudicator design excludes current gulag participants from that week's general-pool selection. Apply selection against the same pre-transition eligibility set, before returning the winner. Exclude previously eliminated teams even if Sleeper still reports their scores. The Word rules say "lowest score in general" for Week 12; the design interprets this as the eligible general pool. Record that interpretation in the versioned season configuration and verify it before activation. Never select the gulag loser twice to satisfy the two-cut requirement.

Paid champions require separate qualifier, beneficiary, and actual participant IDs. In Ben's example, an accepted agreement for Max to take Ben's place puts Max into the contest and applies the roster penalty to Max. It preserves Ben's original qualification and the agreement's $200 separately. It does not eliminate either team when the contract is accepted. A later gulag loss belongs to the actual participant under the accepted ruling. Unaccepted text or an ambiguous contract cannot change official participation.

The 18-team rules have no Gladiator Bowl. Preserve the two-keeper declaration and the actual roster reset as separate facts from Monday's qualification snapshot. Keeper declarations are due Tuesday evening under the league rules, so Monday's job must leave them unknown until supplied. Capture later declarations and resets without replacing the original roster. Weekly $10 survival awards and discretionary meme awards need observed or executed money evidence; an outcome must not fabricate a credited balance.

**Final team means the roster at the event's effective cutoff.** Preserve the scoring lineup from the relevant matchup separately from ownership at that cutoff. A player can be held without starting. Record the event's effective time, the source observation time, and the time we learned the result as different fields. Do not claim second-level precision when only a week is known.

**Money means the league's FAAB balance**, displayed with `$`, matching current league conventions. Store the unit as FAAB. Draft dollars, real-money obligations, and pending contracts are separate fields, not a combined total. Buy-ins, dues, contact information, and private chat data do not belong in the public archive.

**Default player statistic:** count distinct confirmed team-season cuts whose roster at the cut contains the player's stable Sleeper ID. Include starters, bench, and IR. Exclude gulag entries, provisional outcomes, rescinded outcomes, duplicate revisions, and unrelated earlier ownership. Optional filters answer starter-only, a particular season, or gulag-entry questions. “Was ever on a team that eventually died” is a different query requiring ownership history.

## Proposed workflow

1. Capture observations for every team before anything is cut. Add capture to the existing roster sync, writing a new observation when roster, lineup, identity label, or money changes. Preserve scheduled checkpoints at week close and before known gulag resets, plus the entire weekly matchup response needed to reconstruct the scoring roster. Observation failure must be visible; never silently advance the archive's coverage watermark.
2. Assemble a candidate event from official scores and the existing league rules. An explicit Sleeper tag or a chat announcement can flag a candidate, but neither is assumed to be a dependable automatic cut signal yet. A missing roster, a bulk drop, or a zero balance is not an elimination ruling.
3. Automatically compute the outcome when the week's relevant games finish, normally after Monday night. Use the current gulag participants, eligible general-pool teams, season/week rules, and accepted substitutions or score overrides. Store the candidate and its evidence immediately; finalize automatically after the configured score-stability checks. Commissioner input is required only for ties without a configured rule, missing/conflicting outcomes, or discretionary rulings. A fresh snapshot is never delayed while waiting for score stabilization.
4. Choose the best evidence for the cutoff. Prefer a captured observation at the relevant boundary, supported by the weekly matchup and transaction history. A “last observed before cutoff” snapshot is labelled as such unless completeness checks establish no intervening changes. Never use a newer empty roster as proof the team died with no players.
5. In one database transaction, publish the confirmed event, snapshot revision, player rows, and current elimination projection. Rendering or message delivery happens after that commit. A failed notification cannot erase or repeat the event.
6. Implement the necessary deterministic Weekly Adjudicator outcome calculation in the first release and connect it to the recording function. Use one versioned set of league rules, not a second outcome engine inside the archive. Gulag substitutions must name the original qualifier, actual participant, beneficiary, and accepted contract/ruling; paying for protection does not by itself mark anyone eliminated.

Ben clarified that normal weekly cuts should be detected and stored automatically from final scores. The default is automatic capture and adjudication, with commissioner review only for exceptions. No automatic changes to Sleeper or new group-chat announcements are included in this plan.

### Cutoff and finalization

The effective cutoff is the end of the week's relevant games, subject to the season's roster-lock rules. Schedule completion triggers capture; a fixed Monday clock alone must not declare an unfinished week final. Preserve all teams' observations so later score corrections can identify a different cut team without substituting its current roster for its old one.

Record the roster, money, and score evidence at week close, then run the adjudicator's stabilization checks and correction rechecks. Score stability is an operational finalization rule, not a guarantee that no later correction can occur. A changed result appends a revision against the same cutoff evidence.

The cutoff timestamp is an index into retained observations, not a backup of the league. Historical matchup rosters can supplement it, but historical balances and commissioner adjustments require their own saved observations. If capture occurs after the cutoff, retain the true observation time and reconstruction quality instead of labelling later data as an exact cutoff snapshot.

### Proposed weekly job schedule

Ben requested a late Monday-night job. Proposed default times are in `America/Chicago`, following daylight saving time:

- **Monday, 11:30 PM:** start `guillotine-week-close` for the scoring week that is ending. Fetch and persist every team's roster, lineup, FAAB, scores, and relevant accepted rulings. If games are complete, record the provisional gulag/cut outcome and its evidence. Existing change-aware capture should also preserve the first observation after the final game; this scheduled job is a reliable weekly checkpoint.
- **Every 15 minutes while waiting:** recheck unfinished games or unavailable data using persisted pending work, not a long sleeping process. Capture available observations on each attempt, but do not finalize while relevant games remain unfinished. Persist the season and scoring week so retries after midnight or an NFL-week rollover still inspect the right games.
- **Tuesday, 8:00 AM:** fetch fresh scores, compare with the saved week-close observations, and finalize unambiguous outcomes after the stability checks. Also recover a missed Monday run. Reuse the original cutoff roster and money evidence; the morning's current balance is not substituted for Monday's. If games or required outcome inputs remain incomplete, leave the result pending and report the exception.

Keep later material-score-correction checks from the Weekly Adjudicator design. All retry state must survive restarts, and logical season/week/event keys prevent duplicate snapshots and cuts. A delayed or rescheduled game follows actual completion rather than a forced Tuesday deadline.

The job is part of the implementation plan and is not installed yet. Add it to `hermes/guillotine/cron.yaml` with a script wrapper after its CLI and storage exist. Verify the scheduler's actual host timezone at installation; the existing manifest contains Eastern-time comments, so do not paste Central wall-clock times into it without conversion or explicit timezone support.

## Data model

Use the existing `league_events` for published outcome events and add three focused structures:

| Structure | Purpose and important fields |
| --- | --- |
| `private.team_state_observations` | Append-only evidence: league/season/team IDs, Sleeper roster and user IDs, observed timestamp, source week, capture reason, content hash, roster/lineup payload, money inputs, source score values and overrides, schema version. Raw provider payloads stay private. Deduplicate unchanged observations while recording collection health separately. |
| `public.team_event_snapshots` | Versioned public event facts: logical event key, revision, event type, team/season/member IDs, event week, effective cutoff and precision, observed/recorded times, accepted outcome source, public league-event reference, superseded revision, confirmed/retracted status, team/member labels at the time, nullable final FAAB and its as-of time, score, opponent, margin, eligible-pool rank, finish placement where defined, rules version, and separate roster/money/score completeness flags. |
| `public.team_event_players` | One row per snapshot and player: stable player ID, name/position/NFL-team label at the time, owned-at-cutoff, lineup slot/index, started flag, keeper designation when evidenced, and nullable player points. Unique on snapshot ID and player ID. Unknown directory IDs remain present. |

Gulag events also carry `contest_id`, `qualification_week`, `contest_week`, original qualifier, actual participant, beneficiary where applicable, and accepted substitution reference. Terminal events carry an explicit elimination reason. Preserve state before and after each finalized weekly transition, with the expected counts of entrants, distinct cuts, and teams still alive. These fields distinguish a roster reset from a terminal cut without relying on free-text descriptions.

Store actor identity and raw evidence references in the private evidence/audit records. Public snapshots expose only approved league facts. Public roles are read-only; the automation worker publishes through a narrow transaction/procedure that validates season/team associations and revisions. Raw evidence does not become public through a join or view.

Carry an explicit production/test scope on observations and event revisions, including the source event. Public policies and aggregate queries exclude test scope, even if a test was submitted in the main chat. Fixture and rehearsal imports must declare their scope rather than inferring it from a trade-code prefix. Snapshot player rows inherit visibility through their parent snapshot.

Keep the source observations immutable. A correction appends a snapshot revision and links it to the prior revision; a retraction is also a revision. Read the latest revision first, then exclude retracted events. Filtering out retractions before choosing the latest revision would incorrectly resurrect old outcomes. Enforce one effective terminal cut per team-season, while permitting a corrected/retracted cut and a later valid event. A stable logical event key plus revision/input hash makes retries idempotent.

Snapshot roster and finance provenance independently. An official elimination can be certain while its money history is missing. Null means unknown; zero requires evidence. The existing FAAB derivation clamps usage to the league budget, so the archive must retain raw inputs and audit that calculation against league balances before treating it as historical truth. Do not silently clamp unusual balances in the archive.

Player rows cover the union of owned players and the scoring lineup. Preserve both flags when the sets differ; do not infer ownership at the cutoff solely from a player having started earlier in the week.

## Roster and money reconstruction

For future events, collect before reset/release, then verify against the scoring week's roster and observed movements. If a drop occurs between polls, reconstruct only when a known baseline and a complete, ordered set of moves explain the change. Otherwise mark the roster partial and retain the closest observation. Preserve transaction source revisions or raw responses used in any reconstruction so a later sync cannot change its evidence.

For FAAB, retain the directly observed balance and its timestamp. Reconstruct an event-time balance only from a known baseline and complete debits/credits: draft conversion, waiver bids, executed transfers, survival awards, meme awards, and commissioner adjustments. Do not add a registered chat trade and its matching Sleeper transfer twice. An announced contract is not proof the balance changed. Phase one does not require building a full accounting ledger; unknown historical balances stay unknown.

For 2026 onward, Sleeper's weekly matchups provide `players`, ordered `starters`, scores and overrides, alongside separate roster and transaction endpoints. Retain these inputs prospectively to support event-time evidence. No pre-2026 backfill is planned. Source: [Sleeper API](https://docs.sleeper.com/).

Use stable Sleeper user/player IDs and season-specific roster IDs to join across time. Resolve member aliases for questions, but retain labels at the event so a later rename does not rewrite the archived team name. Audit the current username-based member upsert before capture launches to prevent renamed users becoming duplicate people.

## Read behavior and examples

Implement deterministic repository functions before connecting a language model:

- `team_exit(team, season)` returns the latest valid cut snapshot, roster, money, and evidence quality.
- `season_eliminations(season)` returns named events in order, including unresolved coverage separately.
- `season_gulag_history(season, team=None)` returns qualifications, actual appearances, substitutions, and contest results separately from cuts.
- `player_eliminations(player_id, season=None, starters_only=False)` counts cut appearances and returns the contributing team/week records.
- `elimination_player_leaderboard(season=None)` ranks the same counts with a coverage summary.

An answer must show its scope: “Across the recorded 2026 cuts…” or “At least N confirmed appearances; two cut rosters are incomplete.” Missing roster data cannot justify a zero count. With no eligible archived cuts, answer that the archive has no recorded cut history, not that the player has never been eliminated.

The planned League Agent calls these tools and words the answer; SQL/Python computes counts, identities, balances, and exclusions. Every answer includes the matching seasons and source records. The screenshot's golf claims are chat banter, not a source for league facts.

The board reads the cut snapshot's roster, money, and final score together. It must not pair frozen players with today's FAAB or this week's player projections. Add gulag-entry and cut markers to the player journey; show later claims/trades as separate events rather than overwriting the cut entry.

## Implementation sequence

### 1. Capture observations before the first reset

Files: `sleeper/sync.py`, `sleeper/roster_state.py`, `sleeper/scores.py`, a new `history/observations.py`, and a new Supabase migration.

Deliver change-aware roster/money observations, week-close matchup capture, completeness metadata, and capture-health monitoring using existing schedules. No cut decisions yet. Verify that a roster cleared after capture remains reconstructible.

### 2. Detect and record weekly cuts automatically

Files: new deterministic adjudicator module, `history/eliminations.py` and `cli/eliminations.py`, CLI registration, scheduled job wiring, and snapshot/player migrations.

Implement the Weekly Adjudicator's outcome rules and game-completion/stability checks, then record finalized events atomically. Capture provisional event evidence as soon as the games finish. Provide preview, inspect, resolve, correct, and retract operations for review and exceptions; an ordinary unambiguous week needs no manual confirmation. Manual rulings identify the commissioner, event week/type/cutoff, evidence observation, and reason. Build gulag-entry and terminal-cut examples, including a substituted participant, plus a full season simulation.

### 3. Replace the incomplete freeze path

Files: `sleeper/sync.py`, `sleeper/roster_state.py`, `apps/web/src/board/fetchers.ts`, board types and `derive/join.ts`.

If any 2026 `final_rosters` rows appear before rollout, migrate them as observed snapshots with explicitly unknown money and unverified cutoff fidelity. Do not manufacture cutoff timestamps or import pre-2026 rows. Switch consumers to the latest valid cut snapshot, then retire the first-observed automatic freeze for new cuts. Keep current holdings and team state for live operations; archived views use the snapshot. Do not maintain two competing official cut records.

### 4. Ship queryable history

Files: new history query repository and CLI commands; player fetchers/types and `apps/web/src/player/derive/journey.ts`; the League Agent tool registry when implemented.

Deliver the player count, team final roster/balance, season cut list, and source/coverage display. This phase works through CLI and the website even if the general chat agent is not ready.

### 5. Continue the archive each season

For 2027 and later, create the new season's configuration, verify its league/team identity mapping and rules, and start capture before the first games or roster resets. Preserve prior archived seasons unchanged. Cross-season queries aggregate only recorded seasons from 2026 onward and disclose any capture gaps. There is no historical backfill phase.

## Acceptance tests and rollout gates

- A team is captured, cut, then emptied and renamed. Its archived roster, labels, score, and money remain unchanged.
- Gulag entry and final elimination have different rosters. Both survive; only the terminal cut affects the default player count.
- Week 1 produces exactly two qualifications for the Week 2 contest, zero eliminations, and 18 teams still alive. No final-roster freeze, elimination date, or player cut count is created by qualification or the subsequent keeper reset.
- Week 2 resolves the contest qualified in Week 1, cuts only its loser, returns its winner, and selects the next two from the eligible general pool. Seventeen teams remain alive. Sleeper's ordinary head-to-head pairings do not determine the separate gulag result.
- Week 12 resolves the contest qualified in Week 11, produces two distinct cuts, leaves six teams alive, and schedules no further gulag. Weeks 13 through 16 leave five, four, three, and two teams; Week 17 records one champion and one championship loss.
- The synthetic 18-team season has cut counts of 0 in Week 1, 1 each in Weeks 2 through 11, 2 in Week 12, and 1 each in Weeks 13 through 17. It ends with 17 distinct terminal eliminations and one champion. A missing or extra cut fails the transition validation.
- A gulag winner can qualify again in a later week. Record each contest independently, without treating survival or repeated entry as a cut.
- A player is cut with team A, claimed by B, and cut again. Two team-season appearances are counted; duplicate syncs and correction revisions add none.
- A player traded away before the cutoff is excluded even if they played for that manager earlier. A benched or IR player held at the cutoff is included by default.
- A late elimination tag, an empty post-release roster, missing points, and missing FAAB produce explicit gaps rather than fabricated zeros.
- A stat correction changes the cut team. The old event is retracted/superseded, current status and archive agree, and aggregate counts change once.
- A paid gulag substitution records qualifier and participant separately and applies the actual accepted ruling.
- Ben qualifies and pays Max $200 under an accepted substitution. Max receives the gulag penalty and participates; Ben retains qualification history but receives no actual gulag appearance or cut from Max's result. If Max loses, only Max's cut roster contributes to player cut counts. A conflicting or unaccepted agreement leaves participation unresolved.
- An ordinary completed week finalizes without a commissioner action. The lower-scoring gulag participant is evaluated separately from general-pool qualifiers; direct-cut and double-cut weeks use their own rules. Week one does not create a terminal cut.
- A delayed game prevents premature finalization; ties or missing scores enter an unresolved state while all available roster and money observations remain saved.
- Repeated runs, concurrent confirmation, transaction rollback, and a failed notification never create duplicate cuts or half-written snapshots.
- Same-named players, retired/unknown player IDs, member renames, and cross-season roster IDs resolve without collisions.
- The same money transfer in chat and Sleeper is counted once; manual bonus gaps prevent unsupported balance reconstruction.
- Public clients cannot read raw observations, sender handles, dues, or private evidence; test events never enter public counts.
- Cross-season answers and leaderboards say “since 2026,” exclude pre-2026 records, and disclose capture gaps within the supported seasons.

Run synthetic fixtures first, then shadow one week using read-only league inputs. For the first real event, compare the preview to Sleeper and the commissioner's ruling before clearing/releasing players. Archive and query correctness do not depend on iMessage inline replies or the video generator.

## Open decisions

Normal cut detection is automatic. The implemented schedule uses continuous two-minute capture, Monday 11:30 PM Central processing, 15-minute retries, and Tuesday 8:00 AM verification after 30 minutes of stable scores. Week 12 follows the existing adjudicator design's general-pool eligibility rule. Commissioner rulings record substitutions explicitly. Exact roster-reset and keeper timestamps remain unavailable, so entry snapshots disclose partial coverage. The archive does not schedule keeper deadlines.

Other defaults are explicit: preserve both gulag-entry and cut rosters; treat money as FAAB; default player counts to ownership at the cut; start in 2026 and continue forward, with no pre-2026 backfill. Optional acquisition-cost attribution, rankings since 2026, and recap videos can build on these records later.
