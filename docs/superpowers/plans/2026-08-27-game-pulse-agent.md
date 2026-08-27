# Game Pulse Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Post factual after-game standings and reproducible survival estimates after Thursday, Sunday, and Monday game windows.

**Architecture:** A provider-neutral projection repository feeds a deterministic NumPy Monte Carlo engine. Game-window scheduling, coverage gates, factual fallback, persistence, and rendering surround the engine; Weekly Adjudicator remains the only official ruling source.

**Tech Stack:** Foundation Python package, NumPy 2.5.2, PostgreSQL, Supabase Cron/Queues, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-game-pulse-agent-design.md`

## Global Constraints

- Complete the foundation and Weekly Adjudicator engine before this plan.
- Survival percentages are estimates, not official decisions.
- Require projections for at least 95 percent of rostered unplayed starters.
- Missing projections never become zero projected points.
- Use whole percentages and preserve model/source/input versions.
- Monday output is explicitly provisional.
- Do not send stale output after a newer window or final weekly ruling exists.

---

### Task 1: Projection contract and existing Supabase coverage audit

**Files:**
- Create: `agents/game-pulse/agent.yaml`
- Create: `packages/league-automation/src/ultimate_guillotine/projections/models.py`
- Create: `packages/league-automation/src/ultimate_guillotine/projections/repository.py`
- Create: `packages/league-automation/src/ultimate_guillotine/projections/coverage.py`
- Create: `packages/league-automation/tests/projections/test_coverage.py`
- Create: `scripts/audit_projection_coverage.py`

**Interfaces:**
- Consumes: existing `player_projections` table if present, current Sleeper starters/game status.
- Produces: `PlayerProjection`, `ProjectionSnapshot`, `coverage_report(snapshot, starters)`.

- [ ] **Step 1: Write failing coverage tests**

```python
def test_coverage_passes_at_ninety_five_percent() -> None:
    report = coverage_report(projected_ids(range(95)), unplayed_ids(range(100)))
    assert report.ratio == Decimal("0.95")
    assert report.usable is True


def test_missing_projection_is_not_zero() -> None:
    report = coverage_report(projected_ids([1]), unplayed_ids([1, 2]))
    assert report.missing_player_ids == (2,)
    assert report.usable is False
```

- [ ] **Step 2: Run tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/projections/test_coverage.py -v`

- [ ] **Step 3: Add NumPy and implement projection models**

Add `numpy==2.5.2` to `packages/league-automation/pyproject.toml` and lock. Projection fields are provider name, provider player ID, Sleeper player ID, week, mean points, standard deviation, game start, fetched time, and source version. Use `Decimal` at storage boundaries and convert to float only inside the simulation array.

- [ ] **Step 4: Implement the audit script**

The script checks whether the old table exists, prints only counts/coverage/source dates, and exits 0 only when a 2026 validation week has current data and at least 95 percent coverage. If the old schema differs, write a read-only adapter; do not mutate it during audit.

- [ ] **Step 5: Verify and commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add agents/game-pulse packages/league-automation/pyproject.toml uv.lock packages/league-automation/src/ultimate_guillotine/projections packages/league-automation/tests/projections scripts/audit_projection_coverage.py
git commit -m "feat: validate survival projection coverage"
```

### Task 2: Deterministic survival simulation

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/pulse/models.py`
- Create: `packages/league-automation/src/ultimate_guillotine/pulse/simulate.py`
- Create: `packages/league-automation/tests/pulse/test_simulate.py`

**Interfaces:**
- Consumes: current scores, remaining player distributions, Weekly Adjudicator phase/state.
- Produces: `simulate_survival(inputs, seed, simulations=50_000) -> SurvivalResult`.

- [ ] **Step 1: Write failing seeded simulations**

```python
def test_same_seed_replays_exact_probabilities() -> None:
    first = simulate_survival(simple_inputs(), seed=20260901, simulations=10_000)
    second = simulate_survival(simple_inputs(), seed=20260901, simulations=10_000)
    assert first == second


def test_current_gulag_probability_means_gulag_loss() -> None:
    result = simulate_survival(gulag_inputs(team_a_mean=20, team_b_mean=0), seed=4, simulations=20_000)
    assert result.teams["team-b"].adverse_event == "gulag_elimination"
    assert result.teams["team-b"].survival_probability < Decimal("0.05")
```

- [ ] **Step 2: Run tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/pulse/test_simulate.py -v`

- [ ] **Step 3: Implement the simulation**

Use `numpy.random.default_rng(seed)`. Draw non-negative remaining-player totals from each provider distribution, add completed points, and call a vectorized phase-specific adverse-event selector matching Weekly Adjudicator rules. Return whole-probability inputs at full precision; round only in the renderer.

Record simulation count, seed, model version `2026.1`, projection source/version, score snapshot ID, and SHA-256 input hash.

- [ ] **Step 4: Add phase tests and verify**

Cover incoming gulag risk, current gulag loss, week-12 general-pool cut, direct cut, no players remaining, and eliminated-team exclusion.

Run: `pnpm test:agents && pnpm lint:agents`

- [ ] **Step 5: Commit**

```bash
git add packages/league-automation/src/ultimate_guillotine/pulse packages/league-automation/tests/pulse
git commit -m "feat: simulate weekly survival odds"
```

### Task 3: NFL game-window trigger and stale-job rules

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/pulse/windows.py`
- Create: `packages/league-automation/tests/pulse/test_windows.py`
- Create through CLI: `supabase/migrations/<generated>_game_pulse_cron.sql`

**Interfaces:**
- Consumes: normalized NFL schedule, Sleeper NFL state, score snapshots.
- Produces: `due_window(now, games, snapshots) -> GameWindow | None` and queued `game-pulse.run` jobs.

- [ ] **Step 1: Write failing window tests**

```python
def test_no_job_on_day_without_relevant_games() -> None:
    assert due_window(wednesday_noon(), games=[], snapshots=[]) is None


def test_postponed_game_delays_window() -> None:
    window = due_window(original_end_plus_20m(), games=[postponed_game()], snapshots=[])
    assert window is None


def test_older_window_is_stale_after_final_ruling() -> None:
    assert is_stale(thursday_job(), final_week_state()) is True
```

- [ ] **Step 2: Implement dynamic window logic**

Group relevant games into Thursday, Sunday, and Monday windows by actual schedule. A window becomes due after its final game is complete and a newer Sleeper score snapshot exists. A job key is `game-pulse:<season>:<week>:<window>:<score-snapshot-id>:<model-version>`.

- [ ] **Step 3: Create Cron migration**

Run `supabase migration new game_pulse_cron`. Use `cron.schedule` to call a database enqueue function every five minutes during the active NFL season. The function creates no duplicate job key. Do not schedule fixed Thursday/Sunday/Monday send times.

- [ ] **Step 4: Verify and commit**

Run: `supabase db reset && supabase test db && pnpm test:agents`

```bash
git add supabase packages/league-automation/src/ultimate_guillotine/pulse packages/league-automation/tests/pulse
git commit -m "feat: schedule dynamic Game Pulse windows"
```

### Task 4: Persist snapshots and render factual fallback

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/pulse/repository.py`
- Create: `packages/league-automation/src/ultimate_guillotine/pulse/render.py`
- Create: `packages/league-automation/tests/pulse/test_render.py`
- Create through CLI: `supabase/migrations/<generated>_survival_snapshot_details.sql`

**Interfaces:**
- Consumes: `SurvivalResult` or factual-only score state.
- Produces: persisted snapshot and signed Game Pulse body.

- [ ] **Step 1: Write failing renderer tests**

```python
def test_renderer_uses_whole_percentages_and_as_of_time() -> None:
    body = render_pulse(result(probability="0.734"))
    assert "73%" in body
    assert "73.4%" not in body
    assert "Estimates as of" in body


def test_factual_fallback_contains_no_percent_sign() -> None:
    body = render_factual_pulse(score_state(), reason="projection coverage 82%")
    assert "% survival" not in body
    assert "Projections unavailable" in body
```

- [ ] **Step 2: Create detail migration and repository**

Run `supabase migration new survival_snapshot_details`. Add normalized `survival_team_results` referencing `survival_snapshots`, with unique `(snapshot_id, team_id)`, indexed team ID, current points, players remaining, projected finish, adverse event, and survival probability constrained from 0 through 1.

Enable RLS, grant `anon`/`authenticated` select with an explicit public-read policy, and grant `automation_worker` select, insert, and update on `survival_team_results` plus usage/select on its sequence; grant no delete.

- [ ] **Step 3: Implement rendering bands**

Render `Immediate danger`, `Live but vulnerable`, `Strong position`, and `Finished` bands using deterministic thresholds. Include current points, remaining-player count, projected finish when available, whole survival percentage, score/projection timestamp, and signature. Monday begins with `Provisional`.

- [ ] **Step 4: Verify and commit**

Run: `supabase db reset && supabase test db && pnpm test:agents && pnpm lint:agents`

```bash
git add supabase packages/league-automation/src/ultimate_guillotine/pulse packages/league-automation/tests/pulse
git commit -m "feat: persist and render Game Pulse snapshots"
```

### Task 5: Worker handler, self-test, and production gate

**Files:**
- Create: `agents/game-pulse/runner.py`
- Create: `packages/league-automation/tests/pulse/test_runner.py`
- Create: `packages/league-automation/tests/fixtures/pulse/live_week.json`
- Create: `docs/runbooks/game-pulse.md`
- Modify: `services/mac-worker/main.py`

**Interfaces:**
- Consumes: `game-pulse.run` jobs.
- Produces: one persisted snapshot and at most one outbound message per unique window/input/model.

- [ ] **Step 1: Write failing runner tests**

```python
async def test_low_coverage_uses_factual_fallback(runner, delivery) -> None:
    await runner.handle(job_with_coverage("0.94"))
    assert "Projections unavailable" in delivery.reservations[0].body


async def test_stale_job_sends_nothing(runner, delivery) -> None:
    result = await runner.handle(stale_thursday_job())
    assert result.status == "stale"
    assert delivery.reservations == []
```

- [ ] **Step 2: Implement and register the handler**

The runner fetches current inputs, checks staleness and coverage, simulates when allowed, persists first, then reserves delivery. It never calls a language model.

- [ ] **Step 3: Replay fixture and self-test messages**

The fixture covers Thursday, Sunday, Monday, projection failure, postponed game, week-12 dual risk, and a direct-cut week. Run each twice and assert one outbound per unique window. Send all message variants to the self-test chat.

- [ ] **Step 4: Verify and enable production**

Run: `pnpm test:agents && pnpm lint:agents && supabase test db && python3 scripts/mac-mini/doctor.py`

Enable production only after the live projection audit passes 95 percent and one shadow week completes.

- [ ] **Step 5: Commit**

```bash
git add agents/game-pulse services/mac-worker/main.py packages/league-automation/tests/pulse packages/league-automation/tests/fixtures/pulse docs/runbooks/game-pulse.md
git commit -m "test: qualify Game Pulse for production"
```
