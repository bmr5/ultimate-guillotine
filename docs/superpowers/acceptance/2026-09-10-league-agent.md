# League Agent acceptance status, 2026-09-10

Deployment update: Ben separately authorized activation in both registered chats.
The new listener is live on Astra. See the [rollout record](2026-09-10-league-agent-rollout.md)
for current operational evidence. The original five-question acceptance below remains partial;
deployment does not replace its outstanding transaction-history and phone checks.

Task 19 live acceptance is **PARTIAL**. All five questions and the follow-up produced actual GPT-6 Astra answers without correction retries. Question 4 missed the required transaction-history lookup; iPhone and operational gates remain open. [Read the exact replies and full write-ups](2026-09-10-league-agent-replies.md). Earlier authentication blocker observations below are historical. This is not rollout approval.

## Live test session

The fixture smoke test returned an actual Astra answer in 15.65 seconds: "Member01 has the most FAAB remaining: $960." The existing isolated profile authenticated through OpenAI's device-code flow; no credentials were copied from another profile.

The worktree still has no `.env`. A test-only entry point in `.superpowers/sdd/2026-09-10-league-agent/live_acceptance.py` reads the existing main-repository configuration in memory, pins GPT-6 Astra, disables delivery and forces all database connections read-only. The isolated MCP launcher uses it temporarily for real-data testing. Production source, the default bot profile and the live listener are unchanged. This adapter does not establish readiness of the production configuration.

Real MCP connected in 1,268 ms with all eleven tools. Preflight reported season 2026, week 1, eighteen active teams and data age 26 minutes. Ben and Kyle resolved uniquely to public labels Ben R and Kyle. Exact transcripts, timings, session IDs and artifact sizes are being saved under `.superpowers/sdd/2026-09-10-league-agent/live-acceptance/`.

The first three questions succeeded with one model call each and no correction. Winners matched `season_results`; FAAB leader matched the snapshot; bottom-five rankings and roster caveats matched the current projections and rosters. Both complex questions and the follow-up also succeeded, producing three HTML reports. The resumed session preserved both original and follow-up turns. No answer was rejected and no correction turn was needed.

The initial RB reply took 371.02 seconds, the Bowers reply 286.68 seconds and the follow-up 171.48 seconds. These are measured latencies, not a claim of acceptable chat responsiveness. The RB session did not call `transactions`: current free-agent status was verified, but Kyle's actual drop was not. Prices in proposals are labeled suggestions, not observed offers. The controller checked core league facts and continuity, but did not independently verify every external web claim.

All three HTML reports rendered at a 390 by 844 pixel browser viewport without horizontal overflow, scripts or embedded remote media. First viewports were visually inspected. An actual iPhone/Messages check remains NOT RUN. The temporary isolated MCP launcher was restored after testing; the local preview server was stopped. Production source, listener, default profile and league records were unchanged.

## Final offline verification

The consolidated final fix wave addressed all eight Important finding groups in
`.superpowers/sdd/2026-09-10-league-agent/final-review.md`. The fresh GPT-6 Astra scoped review
approved every finding and both wording fixes, with no new breakage. Its report is
`.superpowers/sdd/2026-09-10-league-agent/final-rereview.md`. This completes offline review only.
Evidence and source/test references are in
`.superpowers/sdd/2026-09-10-league-agent/final-fix-report.md`.

On 2026-09-10, from the existing `league-agent` worktree, with
`UV_CACHE_DIR=/private/tmp/league-agent-uv-cache`:

- `pnpm test:agents`: **1,385 passed, 180 skipped, 1 warning in 16.19 seconds**.
  The warning is the existing Starlette/AnyIO deprecation warning.
- `pnpm lint:agents`: **All checks passed**.
- `git diff --check`: clean. The new regression files also have no trailing whitespace.
- Covering agent suite: **217 passed, 22 skipped**. Added cases cover fresh reads after both
  model attempts, delivery privacy, queued follow-ups, session failures, aggregate proposal
  balances, player identities, configured self-sender identity, and public survival results.
- Survival SQL was checked against the migrations and existing summary writer. The three
  SELECTs passed `EXPLAIN` inside `BEGIN READ ONLY` / `ROLLBACK` against the existing local
  Supabase schema. This inspected query plans only; it did not write or dump league rows.
- After the fixes, the controller reinstalled only the existing isolated profile. The strict
  web-plus-league tool audit passed, and the real fixture MCP probe connected in 700 ms and
  discovered all 11 tools. This made no model call and did not change the default profile.

`TEST_DATABASE_URL` remains unavailable. The 180 skipped tests are not a database integration
pass. New fixture and SQL-contract tests cover the affected reads; no test used production data.
No real model, authentication, credential copying, messaging, migration, listener, or promotion
action occurred in that historical fix wave. Live testing was subsequently authorized and completed as recorded above.
The iPhone check and observation/signoff gates remain open; authentication is now working.

## Evidence available

The Codex continuation entries in `.superpowers/sdd/2026-09-10-league-agent/progress.md` record the following checks. These are earlier observations, not checks repeated for this document.

- Task 15 completed a real isolated profile installation and reinstall with the strict web-plus-league tool policy. The real fixture MCP probe reported `Connected` in 829 ms and discovered all 11 league tools. This does not establish authenticated model or web research success.
- The existing isolated profile is `.superpowers/sdd/2026-09-10-league-agent/hermes-live-profile` within this worktree. The default global profile was not installed in this session; its location is outside the session's write permissions.
- A separate controller check used `Settings(_env_file="/Users/benray/Documents/ultimate-guillotine/.env")` and set `conn.read_only = True`. It returned season 2026, week 1, 18 teams alive, and an age of 8 minutes. That age describes the earlier check, not current freshness. No league records were written.
- An Astra fixture CLI smoke test exited 1 with `AIUnavailable`. The sanitized direct Hermes diagnostic reported `No Codex credentials stored` and required `hermes auth`. It produced no model answer. Further model retries stopped.
- The saved bot model remains `gpt-5.6-sol`. Development and review agents in the Codex continuation use GPT-6 Astra. The smoke test attempted the explicit test override `HERMES_MODEL=gpt-6-astra`; it did not fall back to Sol or copy credentials.
- After Task 18, the offline suite reported 1,351 passed and 180 skipped, with the known Starlette/AnyIO deprecation warning. Task 17 implemented all 17 golden cases plus two plumbing/consistency tests. Offline test results do not establish live acceptance. Live stale-data and partial-coverage variants remain unsupported and explicitly skipped because the separate MCP fixture cannot reproduce those variants.

The worktree `.env` is absent. The main repository `.env` exists; its values were neither read nor printed for this documentation task. The earlier direct database check did not configure the worktree's CLI or MCP process.

## Question 1: past winners

Prompt: `@bot who has won the league in every year?`

Asker: Ben R.

Status: ANSWER ACCEPTED. 22.55 seconds, one model call, zero correction retries, no artifact. The reply matched the public history for 2019–2025, including Ben R and Daniel as 2022 co-champions. Session `20260910_172627_d2cc1d`. Exact answer in the linked reply report.

## Question 2: current FAAB leader

Prompt: `@bot who currently has the most FAAB?`

Asker: Ben's public member label.

Status: ANSWER ACCEPTED. 24.49 seconds, one model call, zero correction retries, no artifact. Reply: "Brandon L has the most FAAB, with $710 remaining." Matched the snapshot with no tie. Session `20260910_172710_5a462e`.

## Question 3: bottom five projected teams

Prompt: `@bot who are the bottom 5 projected teams for this week? Note which ones have partial projections or a major injury that makes them likely to make a move.`

Asker: Ben's public member label.

Status: ANSWER ACCEPTED. 41.50 seconds, one model call, zero correction retries, no artifact. Rankings, values, injury flags and missing DEF/K slots matched the snapshot and roster reads. The answer distinguishes league injury designations from independently verified timelines. Session `20260910_172743_db2050`. Exact answer in the linked reply report.

## Question 4: Kyle's RB trade targets

Prompt: `@bot I just had to drop TreVeyon Henderson. What are good RB trade targets around the league from teams that could afford to trade one away — teams with 3 RBs who could fill their flex, teams projected high enough to survive finding a replacement, or a 3-team deal if that works better?`

Asker: Kyle's public member label.

Status: ANSWER ACCEPTED, ACCEPTANCE GAP. 371.02 seconds, one model call, zero correction retries. Report `kyle-s-rb-trade-targets-real-surplus-versus-affordable-downg-week-1.html`, 16,434 bytes. Identified Irving, Dowdle and Swift with seller incentives and a three-team alternative; checked trade arithmetic and described its limits. The session did not call `transactions`, so it did not establish Kyle's drop event. Session `20260910_172839_ecd9ad`. Phone-width browser check passed; actual iPhone NOT RUN.

## Question 5: holding Brock Bowers

Prompt: `@bot I want to find a safe roster to hold Brock Bowers for me this week while he's injured, and what it would cost in FAAB. Or tell me if I'm better off holding him through the injury and playing without a defense.`

Asker: Ben's public member label.

Status: ANSWER ACCEPTED. 286.68 seconds, one model call, zero correction retries. Report `bowers-parking-daniel-first-nick-r-second-holding-as-the-fal-week-1.html`, 13,868 bytes. Suggested 10-FAAB custody/DEF swaps with Daniel or Nick R, compared holding, and correctly identified the existing Max protection record's missing detailed terms. Suggested fees were not presented as market rates. Session `20260910_172946_080993`. Phone-width browser check passed; actual iPhone NOT RUN.

## Follow-up to question 4

Prompt: `what about a two-week rental instead of buying?`

Asker: Kyle's public member label, using question 4's actual Hermes session ID.

Status: ANSWER ACCEPTED; SESSION CONTINUITY PASSED. 171.48 seconds, one resumed model call, zero correction retries. The original and follow-up are both present in `20260910_172839_ecd9ad`, and the client returned the same session. Report `two-week-rb-rentals-temporary-swaps-not-permanent-sales-week-1.html`, 11,905 bytes. The answer adapted the original proposals to temporary swaps and disclosed missing Week 2 projections. Phone-width browser check passed; actual iPhone NOT RUN.

## Remaining setup and user-run commands

See [the Task 18 runbook](../../runbooks/mac-mini.md#10-league-agent-rollout) for profile setup, sender contacts, dry runs, and promotion gates. The following commands are instructions for Ben's Terminal. They were not executed for this documentation task.

Authenticate the existing isolated profile with the intended Codex provider:

```bash
cd /Users/benray/Documents/ultimate-guillotine/.claude/worktrees/league-agent
export UV_CACHE_DIR=/private/tmp/league-agent-uv-cache
export HERMES_LEAGUE_PROFILE_HOME=/Users/benray/Documents/ultimate-guillotine/.claude/worktrees/league-agent/.superpowers/sdd/2026-09-10-league-agent/hermes-live-profile
export HERMES_MODEL=gpt-6-astra
HERMES_HOME="$HERMES_LEAGUE_PROFILE_HOME" hermes auth
```

After authentication succeeds, verify fixture transport and obtain an actual fixture answer:

```bash
UG_AGENT_FIXTURE=1 HERMES_HOME="$HERMES_LEAGUE_PROFILE_HOME" hermes mcp test league
uv run --project packages/league-automation ug agent ask --fixture \
  --as Member01 --out /private/tmp/league-agent-fixture \
  --text "@bot who has the most FAAB"
```

Before real-league commands, configure the worktree's ignored `.env` through your normal secret-management process with the required league settings, including `DATABASE_URL`. Preserve any existing file and settings if one has appeared since this note. Do not paste values into acceptance evidence or print them. Both the CLI and the installed MCP launcher read configuration from this worktree. Keep the exported profile and Astra override above for this acceptance session.

Once that configuration is ready, verify real transport and repeat the read-only overview check. Stop if either fails or returns a data error:

```bash
UG_AGENT_FIXTURE=0 HERMES_HOME="$HERMES_LEAGUE_PROFILE_HOME" hermes mcp test league
uv run --project packages/league-automation python - <<'PY'
from contextlib import closing
import httpx
from ultimate_guillotine.config import load_settings
from ultimate_guillotine.data.database import connect
from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.agent.tools.source import DatabaseSource
from ultimate_guillotine.agent.tools import league

settings = load_settings()
with closing(connect(settings)) as conn, httpx.Client() as http:
    conn.read_only = True
    source = DatabaseSource(conn, SleeperClient(http), settings.sleeper_league_id)
    result = league.league_overview(source)
    if result.get("error"):
        raise SystemExit("League overview failed; resolve the data prerequisite before acceptance.")
    print(result["season"], result["week"], result["teams_alive"], result["age_minutes"])
PY
```

Resolve Ben's and Kyle's public labels from the board. Replace the placeholders below, then run the questions from this worktree in the same configured shell:

```bash
ACCEPTANCE_OUT=docs/superpowers/acceptance/artifacts
uv run --project packages/league-automation ug agent ask --as "<ben>" --out "$ACCEPTANCE_OUT" --text "@bot who has won the league in every year?"
uv run --project packages/league-automation ug agent ask --as "<ben>" --out "$ACCEPTANCE_OUT" --text "@bot who currently has the most FAAB?"
uv run --project packages/league-automation ug agent ask --as "<ben>" --out "$ACCEPTANCE_OUT" --text "@bot who are the bottom 5 projected teams for this week? Note which ones have partial projections or a major injury that makes them likely to make a move."
uv run --project packages/league-automation ug agent ask --as "<kyle>" --out "$ACCEPTANCE_OUT" --text "@bot I just had to drop TreVeyon Henderson. What are good RB trade targets around the league from teams that could afford to trade one away — teams with 3 RBs who could fill their flex, teams projected high enough to survive finding a replacement, or a 3-team deal if that works better?"
uv run --project packages/league-automation ug agent ask --as "<ben>" --out "$ACCEPTANCE_OUT" --text "@bot I want to find a safe roster to hold Brock Bowers for me this week while he's injured, and what it would cost in FAAB. Or tell me if I'm better off holding him through the injury and playing without a defense."
uv run --project packages/league-automation ug agent ask --as "<kyle>" --out "$ACCEPTANCE_OUT" --resume "<actual question 4 session id>" --text "what about a two-week rental instead of buying?"
```

For each completed run, replace its NOT RUN entry with the actual outcome, chat text, artifact filename and byte size if any, measured wall time, and observed verification retry behavior. Omit private data and verbatim web content; cite source URLs. Assess question 4's transaction lookup and question 5's recommendation explicitly. Ben must open any generated files on an iPhone and record the rendering result. No files were delivered through Messages, AirDrop, or a browser for this task.

These dry runs use read-only league access, send no chat messages, and write no league run, session, or answer records. Hermes can maintain its local session state and the CLI can write local artifacts. The dry runs do not require `20260910180000_league_agent.sql`. Hosted migration, listener activation, the dry-run week, iPhone checks, the self-test week, and deliberate league-chat promotion remain separate incomplete rollout gates. No migration, listener change, promotion, merge, or push was performed here.
