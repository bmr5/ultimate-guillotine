# League Agent continuation in Codex

This continues the existing build, beginning with the Task 14 review. It does not restart it.
Ben authorized adapting the plan and requires GPT-6 Astra for every task and review.

## Current status

Offline Tasks 14 through 18, Task 19's acceptance-status documentation, and the final fix/review
are complete. Every continuation implementer and reviewer used GPT-6 Astra. Final verification
reported 1,385 passed, 180 database-gated tests skipped, one known warning, and clean lint.
The final scoped review addressed all eight Important groups and both wording fixes with no
new breakage. Real isolated fixture MCP connected with all eleven tools after the fixes.

Original Task 19 live acceptance is partial. Authentication now works, and all five real questions
plus the actual follow-up returned Astra answers without correction retries. Exact replies and
timings are linked from `docs/superpowers/acceptance/2026-09-10-league-agent.md`. Q4 missed the
required transaction-history lookup; database integration, iPhone rendering and rollout remain open.
Do not repeat completed offline tasks. Preserve all uncommitted changes and ignored evidence.

## Authority and workspace

- Binding product spec: `docs/superpowers/specs/2026-09-10-league-agent-design.md`.
- Original plan: `docs/superpowers/plans/2026-09-10-league-agent.md`.
- Exact worktree: `/Users/benray/Documents/ultimate-guillotine/.claude/worktrees/league-agent`.
- Branch: `worktree-league-agent`; resumption HEAD: `a35db40`.
- Canonical ledger: `.superpowers/sdd/2026-09-10-league-agent/progress.md`.
- Use the existing ignored briefs, reports, and review packages in that ledger's directory.
- Tasks 1 through 13 are reviewed and complete. Task 14 was implemented in `5431174`.

Every shell command must name the exact worktree as its working directory. This Codex session has
no EnterWorktree tool. Do not create another checkout, switch to main, or discard ignored files.

## Execution and review

Use the local Superpowers subagent-driven-development method. Dispatch a fresh GPT-6 Astra
implementer for each task, followed by a GPT-6 Astra reviewer checking both spec and quality.
Use isolated task context and the on-disk briefs. Implementers and reviewers do not spawn agents.
Resolve Important findings before proceeding. Fix reviews examine the fix and the prior findings.
Perform one broad final review and one consolidated final fix wave as the original method requires.

Run commands with `UV_CACHE_DIR=/private/tmp/league-agent-uv-cache` in this session. The normal
uv cache is not writable. Baseline: 1602 passed, 181 skipped, one pre-existing Starlette/AnyIO
deprecation warning. DB-backed tests skip without `TEST_DATABASE_URL`; report this explicitly.

The shared Git metadata and the default Hermes profile directory are read-only in this session.
Do not bypass those permissions. Implement and review worktree changes without staging or commits.
Capture a task's changed files in a review package, including untracked files. Identify the base
commit and record that the reviewed changes are uncommitted. Preserve task reports and review
evidence until the user can commit and finish integration. Do not delete the SDD workspace.

## Remaining work

### Task 14: finish the review and fix gap-fill lifecycle

The first review found a plan-mandated defect: gap-fill returns while its daemon worker has
accepted questions. Their run reservations persist, but the process can exit without answering.
Add explicit worker queue completion and have gap-fill wait for its own accepted jobs in a
finally block. Keep the live listener asynchronous and startup reconciliation exclusive to
listener main(). Cover normal completion, replay failure, and worker exception bookkeeping.

### Task 15: build and verify the Hermes profile

Use the existing Task 15 brief for SOUL, playbook, MCP launcher, and installer requirements.
Check the installed Hermes CLI implementation rather than assuming the plan's command syntax.
Verify the effective tool list, not merely a short list of disabled toolsets. The spec permits
web and the league MCP only. The original plan additionally enables skills and todo; local
Hermes puts skill_manage in the skills toolset, which permits writes and contradicts that boundary.
Keep the versioned playbook file, include its instructions in the installed SOUL if needed, and
keep write-capable skills tools disabled. Do not let the model modify its own instructions.

The installer should accept `HERMES_LEAGUE_PROFILE_HOME` for a custom destination, matching the
application setting, with the original named profile as the default. Verify installation using
a temporary destination and stubbed external commands. Installing the default profile requires
the user's Terminal because that directory is outside this session's writable roots.

Real-runtime checks found that Hermes requires a TTY for its read-only tool summary, filters
fixture/cache variables out of MCP subprocesses, and restores native kanban independently of
the displayed tool list. The installer now handles the bounded summary call, explicitly passes
dynamic fixture/cache settings, disables kanban, and audits the exact effective toolsets.
Both a fresh isolated install and a reinstall passed with all eleven MCP tools discovered.

### Task 16: add the dry-run and answer-history CLI

Follow the existing brief. Preserve lazy MCP imports from Task 12. Printing delivery methods
must accept reply_to. Match public labels as well as aliases. Keep dry-runs unable to send or
write league records. Report failure through the CLI exit status and close resources it owns.
Permit the configured league profile location for fixture dry-runs too, without requiring DB
credentials. Verify fixture output, artifacts, follow-up session forwarding, and failure behavior.

### Task 17: add the offline and live golden questions

Follow the seventeen cases in the brief, preserving existing fake names. Adapt assertions to
the actual reply_to delivery tuples. Assert the exact expected message and attachment counts,
run status, input version, privacy invariants, and follow-up resume behavior. The original canned
execute-trade refusal claims that the agent will log the trade; remove that inaccurate promise.
Keep live mode opt-in and use the configured profile path. Report unavailable live prerequisites
as unavailable, never as acceptance success.

Live follow-up tests must seed and resume a real session, and honor `HERMES_MODEL`. The fixture's
injured player is Bench 05-0. Keep the stale/coverage variants offline and explicitly skip them
in live mode until the separate MCP fixture can reproduce those variants; default data is not
evidence for those cases. The fixture CLI still needs a model; only offline tests substitute one.

### Task 18: remove the superseded Advisor and update documentation

Move the snapshot, pricing, fixture, and surviving tests as listed in the brief. Remove the
temporary `test_math_matches_advisor.py` and obsolete Advisor CLI tests too. Rewrite imports using
tracked source/test paths, excluding virtual environments and ignored task evidence. Preserve
unrelated registrar and video behavior. Use filesystem edits when Git moves are unavailable.

Include reviewed prior-task source/tests that remain untracked because Git metadata is read-only.
Rename the moved `AdvisorHolding` and `AdvisorTeamState` types to `LeagueHolding` and
`LeagueTeamState`, updating every repository consumer without changing data or pricing behavior.

The runbook must name `20260910180000_league_agent.sql`, preserve the contacts loader instructions,
document exact profile installation and dry-run commands, and retain the self-test-only promotion
gate. Hosted migration and listener promotion are separate operational actions.

### Task 19: acceptance and final review

Run the real-league questions and follow-up from the existing Task 19 brief only after the
profile, model authentication, MCP transport, and read-only league access work. Preserve secrets
in ignored configuration; do not print them. Dry-runs need no hosted migration and send no chat
messages. Record actual outputs, elapsed times, verification retries, and artifact sizes.

If a runtime prerequisite needs an outside-worktree installation, complete all offline work and
final review first, then report the exact remaining command. Mark live acceptance incomplete.
An iPhone rendering check requires Ben to open the files. Do not send them through Messages.

The current isolated profile is `.superpowers/sdd/2026-09-10-league-agent/hermes-live-profile`.
Its real MCP fixture transport works, but an Astra smoke test stops before a model call because
Codex credentials are absent. Do not copy credentials or fall back to another model. Authentication
requires Ben's setup action. A separate read-only database check reached the real league without
copying the main repository's `.env`; the worktree still needs its own configuration for a full
real-league MCP run. Record the five questions and follow-up as not run until those prerequisites
are met, with no invented answers or artifacts.

The final review must address Ruling 20: re-read the snapshot after Hermes returns, fit the
lost-thread prefix within the chat cap, and send restart apologies to ops when the originating
chat is unknown. Include deferred findings from the ledger and all new task changes in review.

Do not push a hosted migration, start or restart the live listener, send messages, promote the
agent to the league chat, merge main, or push branches as part of offline implementation.
Leave the exact worktree and its ignored evidence intact for final acceptance and integration.
