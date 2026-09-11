# League Agent build — handoff

> Deployment update, 2026-09-10: Ben authorized commits and both-chat activation.
> The reviewed Agent and completed main changes are integrated and committed.
> The listener is running from main with Astra and both registered chats enabled.
> See the [rollout record](../acceptance/2026-09-10-league-agent-rollout.md).
> Keep this worktree: the configured authenticated profile and SDD evidence live here.
> The handoff below is historical; its uncommitted/offline-only restrictions are superseded.

> Current status, 2026-09-10: Tasks 14 through 18 are complete. Task 19 live acceptance is partial.
> The consolidated final fixes passed the scoped GPT-6 Astra review. Offline work is complete.
> Final offline tests: 1,385 passed, 180 skipped, one known warning. Authentication now works.
> Five real Astra answers plus a follow-up succeeded. Transaction-history verification, actual iPhone
> rendering and rollout gates remain open. See the acceptance record for exact replies and timings.
> Resume from the [canonical ledger](../../../.superpowers/sdd/2026-09-10-league-agent/progress.md)
> and [acceptance record](../acceptance/2026-09-10-league-agent.md), not the historical Task 14
> instructions below. Changes remain uncommitted in the existing worktree.

## What this is
Replacing the deterministic Trade Advisor with the **League Agent**: one `@bot` in the league iMessage
chat → a Hermes agent session (profile `guillotine-league`) with read-only league tools over MCP plus
web research → a fact-checked chat summary and an attached self-contained HTML write-up; inline
iMessage replies resume the same session; every answer is recorded privately.

- Spec (binding authority): `docs/superpowers/specs/2026-09-10-league-agent-design.md`
- Plan (19 tasks, full code per task): `docs/superpowers/plans/2026-09-10-league-agent.md`
- Method: `superpowers:subagent-driven-development` — fresh implementer per task, task review
  (spec + quality), fix rounds with scoped re-review, ledger for recovery.

## Where the work is
- Worktree: `/Users/benray/Documents/ultimate-guillotine/.claude/worktrees/league-agent`
  branch `worktree-league-agent` (enter with `EnterWorktree(path=<that path>)`; never `cd` to the
  main checkout or use `git -C` — the harness refuses it; never bare `git stash`).
- SDD workspace (git-ignored, on disk): `<worktree>/.superpowers/sdd/2026-09-10-league-agent/`
  - `progress.md` — THE LEDGER. First line names the plan. Read it first; trust it over memory.
    Every ruling (`Ruling N:`), every task's completion line, every deferred minor is there.
  - `task-N-brief.md` / `task-N-report.md` — per-task requirements and implementer reports.
  - `constraints.md` — the plan's Global Constraints, handed verbatim to every reviewer.
  - `review-<base>..<head>.diff` — review packages.
- Scripts (from the superpowers plugin): `.../skills/subagent-driven-development/scripts/`
  `sdd-workspace PLAN`, `task-brief PLAN N`, `review-package PLAN BASE HEAD`.

## State at handoff
- Tasks **1–13 complete and reviewed clean** (some after one fix round each). `origin/main` was
  merged into the branch after Task 10 (merge commit `4f47d1f`); suite 1598 passed / 181 skipped
  at HEAD `6713767`; `pnpm lint:agents` clean.
- **Task 14 (trigger + listener registration) is implemented and committed (`5431174`,
  1602 passed / 181 skipped, lint clean) but NOT REVIEWED** — the pause landed before its
  review. On resume: `review-package PLAN 6713767 5431174`, dispatch the task review
  (brief `task-14-brief.md`, report `task-14-report.md`, constraints `constraints.md`), run
  the fix loop if needed, then Task 15.
- Remaining after 14: **15** Hermes profile (SOUL, skill, MCP launcher script, installer),
  **16** `ug agent ask` / `ug agent answers`, **17** golden question set (offline fake agent +
  live mode), **18** delete the Advisor and move survivors, **19** acceptance run with Ben's five
  questions. Then the final whole-branch review, ONE fix wave, then
  `superpowers:finishing-a-development-branch` (fast-forward `main` — Ben's convention allows it).

## Rulings the remaining tasks depend on (all in the ledger; the essentials)
- **Models:** Ben wants every subagent on **Opus**; Opus hit the account session limit at ~03:xx
  (resets 4:30am America/Chicago) so later subagents ran on the session model. Use Opus again when
  available. `SendMessage` is disabled: fix rounds go to a *fresh* implementer carrying the brief,
  the report file and the findings.
- **Ruling 1 (T14):** startup reconciliation only from the listener's `main()`:
  `build_agent_worker(..., *, reconcile)`, `build_processor(..., agent_worker_factory=None,
  reconcile_agent_runs=False)`; `ug ingest gap-fill` must never fail live runs.
- **`reply_to`:** `DeliveryService.deliver/deliver_attachment(..., *, reply_to=None)` (from main).
  The worker passes `reply_to=job.message.chat_guid` on every send (done in T13); the trigger's
  refusal must too (T14); T16's `PrintingDelivery` and any fake delivery need `*, reply_to=None`.
- **Empty session id:** `AgentReply.session_id` may be `""`; retry passes `resume=session_id or
  None` and resends the full envelope + retry envelope when there is no id (done in T13).
- **Migration name:** `supabase/migrations/20260910180000_league_agent.sql` (NOT `…120000…`,
  which collides with an existing file and would be skipped). The runbook text in T18/T19 must say
  180000. Applying it to the hosted DB (`supabase db push`) is **Ben's call — ask first**. The dry
  run (`ug agent ask`) needs no migration.
- **Ruling 15:** `rules`/`history` tool results carry `source`, not `as_of` (not snapshot-backed).
- **Ruling 3:** `trade_math` reports `projections_complete`; `lineup_delta` does not gate.
- **T15:** the skill must document every `TOOL_NAMES` entry and every artifact utility class
  (`card pro con num tag muted`) in backticks (a test checks); never promise `#anchor` links (no
  `id` attribute survives sanitizing); `text_content` may only scan sanitized HTML.
- **T17:** imports the fakes from `tests/agent/test_trigger.py` and `tests/agent/test_worker.py`
  by name (`FakeContacts`, `FakeDelivery`, `FakeOutbound`, `FakeRuns`, `FakeSessions`, `Timers`,
  `_msg`, `_reply`, …) — keep those names.
- **T18:** also `git rm tests/agent/test_math_matches_advisor.py` (temporary equivalence test);
  the `advisor.*` imports across `agent/` and tests are rewritten by the plan's sed lines.
- **Ruling 20 (final fix wave, not a task loop):** worker should re-read the snapshot *after* the
  Hermes call for verification; budget the `LOST_THREAD` prefix inside the 1,200-char cap; send
  the restart apology to ops (not the configured chat) when the asker's chat is unknown.
- **T19 prerequisites:** `.env` exists at the repo root (main checkout) with `DATABASE_URL`; copy
  it into the worktree root for the live run. Install the profile with
  `bash hermes/guillotine-league/install.sh` (T15 writes it; it copies the ops profile's model
  block, registers `hermes mcp add league --command <profile>/scripts/league_mcp.sh`, disables
  every toolset but `web`, `skills`, `todo`). Ben's five questions are in the T19 brief.

## Commands
- Tests/lint (from the worktree root): `pnpm test:agents`, `pnpm lint:agents`
  (DB-backed tests skip without `TEST_DATABASE_URL`; a local Supabase Docker stack exists on this
  machine — re-apply `20260910180000_league_agent.sql` there before running DB tests).
- Live golden set (after T15/T17): `UG_LIVE_AI_TESTS=1 uv run --project packages/league-automation
  pytest packages/league-automation/tests/agent/test_golden.py -v -x`
- Dry run (T16): `uv run --project packages/league-automation ug agent ask --as <label> --text "…"
  [--fixture] [--out DIR] [--resume <session id>]`
- MCP transport proof: see `task-12-report.md` (stdio client script; works with mcp 2.2.0).

## Gotchas
- The Vercel plugin hook fires "you must run Skill(...)" on `uv run` and many prompts — all
  lexical false positives; ignore.
- `.claude/worktrees` is not git-ignored in this repo: never `git add -A` at the root.
- Other sessions merge to `main` continuously; before finishing, merge `origin/main` again.

## Ledger snapshot (canonical copy: <worktree>/.superpowers/sdd/2026-09-10-league-agent/progress.md)

```
# SDD ledger — plan: docs/superpowers/plans/2026-09-10-league-agent.md

Worktree: .claude/worktrees/league-agent, branch worktree-league-agent, base 2853451 (origin/main).
Spec: docs/superpowers/specs/2026-09-10-league-agent-design.md (read; binding authority).
Model policy: every subagent on Opus — Ben's standing preference; overrides the skill's cheap-model guidance.
Baseline: pnpm test:agents → 1157 passed, 153 skipped (2 pre-existing warnings).

## Pre-flight conflict scan

| Tasks | Produces / consumes | Finding |
| --- | --- | --- |
| T1 ↔ T10 | math.lineup_delta(roster, incoming, outgoing, weeks), replacement_levels, startable ↔ trade_math | signatures agree |
| T2 ↔ T4, T14 | InboundMessage.thread_originator_guid / attachment_names ↔ reconcile-by-filename, follow-up resolution | agree; T2 must keep the `_is_reaction` check now on main (noted in brief) |
| T3 ↔ T13, T14, T16 | AgentSessionRepository.create/touch/get, AgentAnswerRepository.record/recent, RunRepository.set_session/session_id_for/running_ids, OutboundRepository.run_id_for_guid ↔ worker, resolver, CLI fakes | agree |
| T4 ↔ T13, T16 | DeliveryService.deliver_attachment(run_id, agent, filename, data) ↔ worker call, PrintingDelivery | agree |
| T5 ↔ T6, T11, T13 | LeagueAnswer/Report(question)/Facts ↔ render_artifact, verify, worker record | agree |
| T6 ↔ T13 | render_artifact(report, *, asker_label, season, week, source_line, generated_at) | keyword call matches |
| T7 ↔ T13 | Turn(6 fields), build_envelope, retry_envelope, PROMPT_VERSION | agree; dataclasses.replace on frozen Turn is fine |
| T8 ↔ T13, T16, T17 | HermesAgentClient(home, *, model, runner, binary, hang_guard_seconds, extra_env).run(query, *, resume) → AgentReply | agree |
| T9 ↔ T10, T11, T12, T13, T16, T17 | names.*, LeagueSource (9 methods incl. catalog), FixtureSource(week, **snapshot_kwargs) | agree; T17 passes synced_at/coverage_pct which fixture_snapshot accepts |
| T12 ↔ T15, T16 | TOOL_NAMES, FIXTURE_ENV, serve(fixture) | agree; `server.name` attribute on MCPServer unverified — implementer may drop that one assertion |
| T13 ↔ T14, T16, T17 | AgentWorker kwargs, Job(run_id, message, asker, session), AGENT | agree |
| T14 ↔ cli/ingest gap-fill | build_processor(settings, conn, client, delivery, notifier, agent_worker_factory=None) | positional callers unaffected; see Ruling 1 |
| T17 ↔ T14, T13 | imports the fakes from tests/agent/test_trigger.py and test_worker.py by name | names exist in both plans |
| T18 ↔ all | git mv state/pricing/fixture → agent/tools/{snapshot,pricing,fixture}; sed of imports; tests/advisor/fixture → tests/agent/fixture | T10's test import is rewritten by the sed |
| each task | tests vs code it specifies | consistent after the plan's self-review patch (rules topic test, golden outcomes, worker session assertion) |

Ruling 1: `reconcile_startup` must not run from `build_processor` — `ug ingest gap-fill` also builds the processor and would mark the live listener's in-flight runs failed. Decision: `build_agent_worker(..., *, reconcile: bool)` and `build_processor(..., reconcile_agent_runs=False)`; the listener's `main()` passes True. Cost if wrong: a restart-orphaned run stays `running` until the audit notices. Carried into the T14 dispatch.
Ruling 2: fast-forwarding `main` from this worktree may be refused by the worktree guard; if so, main is fast-forwarded once at finish (Ben's convention allows either). Cost if wrong: other sessions see the branch later than usual.

## Progress
Task 1: implemented e0736c3 (DONE_WITH_CONCERNS); reviewer dispatched.
Ruling 3: `lineup_delta` carries no coverage gate (the implementer's concern 1). Per-player projections are public on the board even when a team total is provisional, so a delta computed from them is not a leak; Task 10's `trade_math` reports `projections_complete: snapshot.coverage_ok()` beside its figures so the agent can caveat. Cost if wrong: a lineup change quoted from thin projections.
Ruling 4: `holdings_by_id` stays in math.py; Task 11's `_holder_of` uses it rather than an inline roster walk. Cost if wrong: one unused helper.
Task 1: review → Needs fixes. Important #1 lineup_delta drops the `known` gate (plan-mandated); Important #2 test docstring claims Advisor-equivalence no test pins (plan-mandated). Minors deferred: holdings_by_id untested/unexported (→ T11 exports+uses it), LEAGUE_TEAMS exported but unread, test restates algorithm, key=lambda TypeError fragility, _contenders docstring style, pre-existing starlette DeprecationWarning.
Ruling 5 (on #1): the gate stays out of `lineup_delta` (Ruling 3 stands); the fix is a docstring contract ("callers gate on snapshot.coverage_ok(); this returns a number below it") and a test pinning below-gate-with-points behavior. Cost if wrong: a tool quotes a delta the data layer would have withheld.
Ruling 6 (on #2): add the Advisor-equivalence test now, guarded by pytest.importorskip on the Advisor modules; Task 18 deletes that test explicitly when it deletes the Advisor. Cost if wrong: a test that exists for a few tasks only.
Task 1: fix round 1/5 (3 addressed per implementer, 0 open pending re-review — docstring contract + below-gate pin test, tests/agent/test_math_matches_advisor.py behind importorskip, LEAGUE_TEAMS removed; commits e0736c3..dc533a7). Note for T18: `git rm tests/agent/test_math_matches_advisor.py` when the Advisor goes.
Task 1: complete (commits 2853451..dc533a7, review clean after fix round 1). Deferred minors: test restates algorithm; key=lambda fragility; _contenders docstring style; pre-existing starlette DeprecationWarning; plan/brief text predates the fix on two points (documentation only).
Task 2: dispatched, BASE dc533a7.
Ruling 2 outcome: the worktree guard refuses git -C to the main checkout; main is fast-forwarded once at finish via finishing-a-development-branch.
Task 2: complete (commits dc533a7..f44ec77, review Approved). Deferred minors: untested transferName-missing / empty-originator / multi-attachment branches; double get("transferName"); non-string transferName raises ValidationError (pre-existing class of fragility).
Ruling 7 (Task 2 Important, plan-mandated): `messages_after` asks BlueBubbles for `with=handle` only, so attachment names never come back on the crash-reconciliation path. Task 4 (which owns reconcile-by-filename) must add `attachment` to that `with` parameter and assert it in the respx test. Cost if wrong: an attachment reconcile that silently never matches → a double-sent file after a crash.
Task 3: dispatched, BASE f44ec77.
Task 3: implemented 18d82a8 (DONE_WITH_CONCERNS); reviewer dispatched.
Ruling 8: the migration is `supabase/migrations/20260910180000_league_agent.sql`, not `…120000…` — the plan's timestamp collided with the existing trade_catalog_announcement migration and Supabase keys pending work on version alone, so the second file would be skipped silently. Tasks 18/19 (runbook, acceptance) must name 20260910180000. Cost if wrong: none; the rename is one git mv.
Note: a local Supabase stack runs in Docker on this machine; the implementer ran the DB-backed tests against it (4 passed) with TEST_DATABASE_URL pointed at it. Later DB tasks can do the same.
Task 3: complete (commits f44ec77..18d82a8, review Approved). Deferred minors: create()'s on-conflict branch has no committed test (Task 13 exercises it in production); create() is create-or-resume by name; agent_answers_created_at_idx unused by recent() (orders by id); touch() has no production caller; running_ids exact-equality test is fragile against a shared table. Note: the local Supabase stack had the migration applied then removed — re-apply 20260910180000_league_agent.sql before running DB tests against these tables.
Task 4: dispatched, BASE 18d82a8, carrying Ruling 7.
Task 4: implemented b35ae2b (DONE_WITH_CONCERNS: server grammar of with=handle,attachment unverified; same-name reconcile window inherent); reviewer dispatched.
Task 4 concern 1 resolved: BlueBubbles parseWithQuery splits the `with` query on commas (trim + lowercase) and getMessages checks for an "attachment" token, so with=handle,attachment loads attachments. Verified against the server source, not a live server.
Task 4: complete (commits 18d82a8..b35ae2b, review Approved). Reviewer's Important was the report mis-scoping the `with` risk (gap-fill also calls messages_after); resolved by the server-source check above — comma list, "handle" token still present, so gap-fill attribution is unchanged. Deferred minors: no commit-ordering test for deliver_attachment; failed-then-retry branch uncovered; reconcile test does not assert the row state; filename-not-content matching is inherent.
Task 5: dispatched, BASE b35ae2b.
Task 5: implemented ec1edd0 (DONE_WITH_CONCERNS: removed a no-op try/except that ruff TRY203 rejects; Report.question defaults to "" — the artifact task renders it as given); reviewer dispatched.
Task 5: complete (commits b35ae2b..ec1edd0, review Approved). Deferred minors: extra="ignore" can drop a misspelt facts key silently (e.g. "proposal"); frozen=True is shallow and lists make the models unhashable; REPORT_BODY_LIMIT counts characters (the worker checks rendered bytes); one test asserts its own fixture; Proposal.title has no min_length; several bounds untested.
Task 6: dispatched, BASE ec1edd0.
Task 6: implemented 2ef0fd5 (DONE_WITH_CONCERNS: parents[5] not [4]; attribute_filter must keep nh3's own rel; B008 hoist). Notes for later tasks: text_content fails open after a void dropped tag — only ever scan sanitized HTML (T13 does); `#anchor` hrefs can never resolve because `id` is not allowlisted — T15's skill must not promise anchors. Reviewer dispatched.
Task 6: review → Approved with Important #1 (plan-mandated): text_content fails open after a void dropped tag (<embed>) — unreachable behind the sanitizer today, but exported. Fix round 1 dispatched for it plus minors 2 (external_references blind spots: srcset/poster/data/<base href/string @import), 3 (single-pass token substitution), 4 (empty <ol> when every source is non-https), 6 (rel-branch narrowness tests). Deferred: template lines >100 chars (HTML, verbatim); text_content space-join can split a PII pattern across inline tags; dead `or ""`.
Task 6: fix round 1/5 — implementer committed 9290c64 then hit the Opus session limit while appending its report (resets 4:30am Chicago); subsequent subagents run on the session model (Fable) until then. Ruling 9: this is a harness limit, not a plan defect; Ben asked to continue. Cost if wrong: none beyond the model swap.
Task 6: fix round 1/5 (5 addressed, 0 open; commits 2ef0fd5..9290c64).
Task 6: complete (commits ec1edd0..9290c64, review clean after fix round 1). Deferred minors: srcset yields first candidate only (tripwire semantics); CDATA_CONTENT_ELEMENTS override relies on a stable-but-undocumented stdlib attribute; `#anchor` hrefs never resolve (no id attribute) — T7/T15 prompts must not mention anchors.
Task 7: dispatched, BASE 9290c64 (Fable — Opus limited until 4:30am Chicago).
Task 7: implemented 5f4889b (DONE_WITH_CONCERNS: parents[5]; single-pass re.sub; a message containing the literal MESSAGE>>> marker escapes the fence — reviewer to weigh); reviewer dispatched.
Task 7: review → Needs fixes. Important #1: a message (or label) containing a fence marker escapes the fence. Ruling 10: neutralize the markers inside the member's text (defanged spelling, e.g. `MESSAGE >>>` / `<<< MESSAGE`) in build_envelope and apply the same to asker_label — every envelope stays well-formed and no new refusal path is needed; a marker in a member's message is only ever an injection attempt, so losing verbatim there costs nothing. Cost if wrong: a member who literally types the marker sees it altered in the model's view. Fix round 1 dispatched with minors 2 (raise at import when the version line is missing), 3 (non-greedy token regex), 5 (assert the version comment is stripped) folded in.
Task 7: fix round 1/5 (4 addressed per implementer; commits 5f4889b..178f073; note: artifact.py has the same greedy _TOKEN pattern — deferred minor).
Task 7: fix round 1/5 (4 addressed, 0 open; commits 5f4889b..178f073).
Task 7: complete (commits 9290c64..178f073, review clean after fix round 1). Deferred minors: DEFANGED is a public mutable dict; a BOM-prefixed template fails loud at import (deliberate); artifact.py's _TOKEN is still greedy (harmless). Note for T13: collapse whitespace/newlines in the asker label before building the Turn (a label with a newline could add header lines).
Task 8: dispatched, BASE 178f073 (Fable).
Task 8: implemented a48439b (DONE; note: the hang guard kills hermes but not grandchild MCP processes — inherent); reviewer dispatched.
Task 8: complete (commits 178f073..a48439b, review Approved). Deferred minors: flag order differs from the constraint's literal line (set identical, plan-mandated); uncommitted probes for 0600 mode / raise-path deletion / HERMES_HOME precedence; run() duplicates HermesStructuredClient._run; the hang guard does not kill grandchildren (follow-up: start_new_session + group kill if orphans appear). Note for T13: `AgentReply.session_id` may be "" (no session_id line on stderr) and `run(resume="")` starts fresh — the verification retry must pass `resume=reply.session_id or None` and, when there is no id, resend the full turn envelope followed by the retry envelope so the question is not lost.
Task 9: dispatched, BASE a48439b (Fable).
Task 9: implemented bd9fe47 (DONE; DatabaseSource SQL unexercised locally; int-keyed projection maps become string keys over JSON — note for T12/T15). Reviewer dispatched.
Task 9: review → Needs fixes. Important #1 (plan-mandated): resolve_player's partial tier applies prefer-rostered and picks silently among surname matches. Ruling 11: on the partial tier, more than one candidate is always Ambiguous (candidates listed, rostered ones marked); prefer-rostered stays on the exact tier only. Cost if wrong: one extra clarifying question when two players share a surname. Important #2 (plan-mandated): as_of came from synced_at (newest) while age_minutes came from oldest_synced_at. Ruling 12: as_of = oldest_synced_at in UTC, plus a newest_sync field; age stays on the oldest. Cost if wrong: none. Fix round 1 dispatched. Deferred minors: error results carry no stamp; @tool catch list narrower than its docstring; None-projection rank compaction unstated; fixture join key equals label so the privacy test's join-key branch is weak; DatabaseSource has no DB test yet; Ambiguous truncates at 8 silently; free-agent player() has no projections and differing keys (T12 tool description must say so).
Task 9: fix round 1/5 (2 addressed per implementer; commits bd9fe47..fc1fc95; newest_sync now on every result — T12 descriptions may mention it).
Task 9: fix round 1/5 (2 addressed, 0 open; commits bd9fe47..fc1fc95).
Task 9: complete (commits a48439b..fc1fc95, review clean after fix round 1). Out-of-scope note: trades/resolve.py keeps its own player resolver with prefer-rostered on partial matches (Registrar's; untouched).
Task 10: dispatched, BASE fc1fc95 (Fable), carrying Ruling 3 (trade_math reports projections_complete).
Task 10: implemented da0b022 (DONE; concerns: per-leg FAAB over-budget check, price_history positions from the active pool only, rules topic miss returns the whole file). Reviewer dispatched.
Drift check (after Task 10): origin/main gained ~20 commits (video feature, EOD summary, web) touching bluebubbles.py, delivery.py, run.py, processing.py, cli/main.py and their tests, plus two migrations (20260910190000_player_card, 20260910210000_video_jobs). main's InboundMessage reply fields, send_attachment, deliver_attachment and attachment_hash are verbatim this plan's Task 2/4 code; main also added OutboundRepository.content_for_guid and a video trigger in run.py.
Ruling 13: merge origin/main into worktree-league-agent as its own dispatched task right after the Task 10 review (before Task 11), deduping the identical attachment/reply code and tests, keeping this branch's with=handle,attachment and run_id_for_guid; Task 14 then edits the post-merge run.py. Cost if wrong: a messier merge at finish; none to behavior.
Task 10: review → Needs fixes. Important #1 (plan-mandated): per-leg FAAB check misses a net overdraw and can false-positive on a credited-then-debited side. Ruling 14: replace the per-leg check with a net check per side after the loop — any side whose faab_after < 0 gets one flag naming how far over budget it ends; the message keeps the words "over" and "budget". Cost if wrong: none. Important #2 (plan-mandated): rules/history carry no as_of/age_minutes. Ruling 15: exception recorded — those two read a file and the results table, not the snapshot; stamping them with the snapshot's time would misstate freshness. They carry a `source` key instead ("league-rules.md", "season_results"); the module docstring says so. Cost if wrong: the agent cannot say how old a rules answer is (the file is versioned in git). Fix round 1 dispatched (net check + `holdings_by_id` into math.__all__ + `source` keys). Deferred minors: "former member" for a None id; positions only from the active pool (positions_for not on the protocol); rules/price_history give no "no match" signal; ×5 and projections_complete=False unpinned; IR/taxi incoming counted fieldable; duplicate player legs; negative/non-numeric amounts; history() without season shows []; survival(week=N) lists current eliminations; transactions drop waiver_budget/draft_picks; league.py at 510 lines (split later).
Task 10: fix round 1/5 (2 addressed per implementer; commits da0b022..117e096).
Task 10: fix round 1/5 (3 addressed, 0 open; commits da0b022..117e096).
Task 10: complete (commits fc1fc95..117e096, review clean after fix round 1).
Merge task: dispatched (brief .superpowers/sdd/2026-09-10-league-agent/merge-main-brief.md), BASE 117e096.
Merge task: complete — merge commit 4f47d1f (117e096 + origin/main 676b3cf); nine files reconciled, duplicates collapsed; lint clean; pnpm test:agents 1560 passed / 181 skipped. main had already made the with=handle,attachment change. New facts for later tasks: DeliveryService.deliver/deliver_attachment take `*, reply_to=None` (production answers the self-test chat when the message came from it — the worker must pass the inbound chat_guid); cli/main.py registers modules in a fixed loop (agent needs an import and a slot); run.py registers ping → registrar → advisor → video; main also added migration 20260910220000_video_jobs_chat.sql.
Task 11: dispatched, BASE 4f47d1f (Fable), carrying Ruling 4 (use holdings_by_id).
Note for T13/T14: DeliveryService.deliver(run_id, agent, content, *, reply_to=None) and deliver_attachment(..., *, reply_to=None) — reply_to is the chat the triggering message came from (production answers the self-test chat when the message came from it). The worker passes reply_to=job.message.chat_guid on every deliver/deliver_attachment call; the trigger passes it on the override refusal; the pacing lines too.
Task 11: implemented c070a05 (DONE_WITH_CONCERNS: _PHONE false-positives on three space-separated 3/3/4-digit numbers; holder token echoed into the retry sentence; player_of with an unknown id resolves it as a name). Reviewer dispatched.
Task 11: review → Needs fixes. Important #1 (plan-mandated): join-key scan tokenizes into single words, missing multi-word and possessive keys. Ruling 16: phrase-match (` key ` in the normalized haystack with apostrophes treated as spaces). Important #2 (plan-mandated): problem sentences echo the model's raw token (Unknown/Ambiguous text, the `not {member}'s` sentence) and flow into ops notes. Ruling 17: every problem sentence names players by full_name and members by member_label only; Unknown/Ambiguous become token-free sentences ("the holder given for X matches no member / more than one member"); and verify() post-filters its own list through privacy_problems, replacing any tripping sentence with a category-only one — so the worker may put reasons in ops notes verbatim. Cost if wrong: a slightly vaguer retry hint for the agent. Fix round 1 dispatched with minors 3 (player_pool lookup for an id the directory lacks) and 6 (surface an ambiguous holder as its own problem) folded in. Deferred: free-agent from_member in a leg; hash regex case; per-leg money sums; coverage gaps; _check_leg closure shape.
Task 11: fix round 1/5 (4 addressed per implementer; commits c070a05..213ebeb; note: privacy findings are appended after the post-filter so "mentions dues" survives).
Task 11: fix round 1/5 (4 addressed, 0 open; commits c070a05..213ebeb).
Task 11: complete (commits 4f47d1f..213ebeb, review clean after fix round 1). Deferred minors: apostrophe translation applied to the text but not the key (o'neil); proposal titles are model-written and echoed into sentences (post-filter catches scanned categories only); a join key that is a whole word inside a player name turns an actionable sentence into UNPUBLISHED.
Task 12: dispatched, BASE 213ebeb (Fable).
Task 12: implemented cd621e5 (DONE_WITH_CONCERNS: -> str tools also emit structured_content, doubling each result on the pipe — reviewer to weigh structured_output=False; cleandoc on descriptions). Reviewer dispatched.
Task 12: review → Needs fixes. Important #1 (plan-mandated): `-> str` wrappers registered without structured_output=False make mcp 2.2.0 send each result twice (text + structured_content). Ruling 18: register every tool with structured_output=False and pin it (outputSchema None; structured_content None). Important #2 (plan-mandated): `scope`/`kind` are bare strings; a typo yields a plausible wrong answer. Ruling 19: Literal["starters","roster"] and Literal["permanent","rental","all"] in the wrapper signatures so the schema carries an enum. Fix round 1 dispatched with minors folded in: lazy-import serve in cmd_mcp, drop the dead `log`, describe trades' `limit` and league_overview's coverage flags, one async wire-contract test over server.list_tools()/call_tool(). Deferred: tests call raw closures; report's "never imports psycopg-backed modules" overclaims (import ≠ connect).
Task 12: fix round 1/5 (5 addressed per implementer; commits cd621e5..1f4be10).
Task 12: fix round 1/5 (5 addressed, 0 open; commits cd621e5..1f4be10).
Task 12: complete (commits 213ebeb..1f4be10, review clean after fix round 1). Notes: Literal validation lives at the MCP door only (the dry run's direct callables accept any string — T16 must not assume otherwise); accepted_terms caps at 200 before the member filter (pre-existing).
Task 13: dispatched, BASE 1f4be10 (Fable), carrying: reply_to on every deliver/deliver_attachment; resume=session_id or None with the full turn envelope resent when no id; collapse whitespace in the asker label.
Task 13: implemented 6713767 (DONE_WITH_CONCERNS: restart apology has no chat to reply_to; T14/T16 fakes need *, reply_to=None; LOST_THREAD prefix can exceed 1200; pacer shares the worker RLock; queued timer cancelled at job start; local_time rendered "Thu 10:05am"). Reviewer dispatched.
Task 13: complete (commits 1f4be10..6713767, review Approved). Ruling 20 (for the final fix wave, not a loop): the worker reads the verification snapshot before the Hermes call; the spec says "after the session returns, the worker loads a fresh LeagueSnapshot" — re-read under the lock just before `_checked` (removes a false-rejection window on hour-long runs). Also for that wave: budget the LOST_THREAD prefix inside the 1,200 cap; the restart apology should go to ops when the asker's chat is unknown rather than to the configured chat. Cost if wrong: one extra six-query read per answer. Deferred minors: _busy gap loses a courtesy line; untested notifier/delivery-raise paths; worker.py at 436 lines (pacing could split out); _fail under the snapshot lock holds the lock across an alerts call; tests reach into _busy/_queue.
Task 14: dispatched, BASE 6713767 (Fable), carrying Ruling 1 (reconcile only from main()), reply_to on the refusal, and the post-merge run.py shape.
PAUSED by Ben after dispatching Task 14 (implementer in flight; BASE 6713767). On resume: review Task 14 (review-package 6713767..HEAD), then Tasks 15-19, then the final whole-branch review and the fix wave (Ruling 20 items), then finishing-a-development-branch (fast-forward main).
Task 14: implemented 5431174 (DONE_WITH_CONCERNS: caplog INFO level added; two registrar tests inject a FakeWorker; "disabled exactly once" test retargeted to the agent; factory/reconcile flags keyword-only; matches() does a DB read for untagged replies outside on_error, same as the video trigger). NOT YET REVIEWED — paused. On resume: review-package 6713767..5431174, dispatch the task review, then Task 15.
```
