# Weekly Adjudicator Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deterministically compute and automatically announce every weekly gulag, elimination, cut, correction, and championship transition.

**Architecture:** A pure state machine consumes normalized Sleeper scores, prior finalized state, and explicit override events. Persistence and message rendering wrap the pure engine; no model call participates in outcome selection.

**Tech Stack:** Foundation Python package, Pydantic, PostgreSQL, Supabase Cron/Queues, pytest with historical and synthetic season replays.

**Spec:** `docs/superpowers/specs/2026-08-27-weekly-adjudicator-agent-design.md`

## Global Constraints

- Complete the automation foundation first.
- Use deterministic code only for ranks, gulag selection, eliminations, cuts, and corrections.
- Current gulag teams are excluded from new general-pool selection.
- An unresolved tie, missing mapping, conflicting override, or missing score never produces a public ruling.
- Final results require two stable fresh Sleeper snapshots Tuesday morning.
- Rule times display in `America/Chicago`.
- Repeated inputs create no duplicate state transition or message.

---

### Task 1: Weekly state and scoring models

**Files:**
- Create: `agents/weekly-adjudicator/agent.yaml`
- Create: `packages/league-automation/src/ultimate_guillotine/adjudication/models.py`
- Create: `packages/league-automation/src/ultimate_guillotine/adjudication/rank.py`
- Create: `packages/league-automation/tests/adjudication/test_rank.py`

**Interfaces:**
- Consumes: team IDs and decimal Sleeper points.
- Produces: `TeamScore`, `WeekState`, `RankedScore`, `rank_scores()`.

- [ ] **Step 1: Write failing rank tests**

```python
def test_rank_orders_decimal_scores_without_float_rounding() -> None:
    ranked = rank_scores([score(1, "91.25"), score(2, "91.24")])
    assert [row.team_id for row in ranked] == [2, 1]


def test_rank_reports_exact_tie() -> None:
    ranked = rank_scores([score(1, "88.10"), score(2, "88.10")])
    assert ranked[0].rank == ranked[1].rank == 1
    assert ranked[0].tied is True
```

- [ ] **Step 2: Run tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/adjudication/test_rank.py -v`

- [ ] **Step 3: Implement exact models and ranking**

Use `Decimal`, never binary float, for official scores. `WeekState` contains season, week, active team IDs, current gulag team IDs, eliminated team IDs, prior state version, and rules version. Ranking sorts ascending for danger selection and records exact ties without breaking them.

```yaml
name: weekly-adjudicator
job_type: adjudication.compute
delivery_modes: [disabled, test, production]
rules_version: "2026.1"
```

- [ ] **Step 4: Verify and commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add agents/weekly-adjudicator packages/league-automation/src/ultimate_guillotine/adjudication packages/league-automation/tests/adjudication
git commit -m "feat: model exact weekly scoring state"
```

### Task 2: Encode the 17-week rules state machine

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/adjudication/rules.py`
- Create: `packages/league-automation/src/ultimate_guillotine/adjudication/engine.py`
- Create: `packages/league-automation/tests/adjudication/test_engine.py`

**Interfaces:**
- Consumes: `WeekState`, all active `TeamScore` values.
- Produces: `AdjudicationResult` with status, incoming gulag, eliminated teams, survivors, and reasons.

- [ ] **Step 1: Write one failing test for each rules phase**

```python
def test_week_one_sends_bottom_two_to_week_two_gulag() -> None:
    result = adjudicate(state(week=1, active=range(1, 19)), descending_scores(18))
    assert result.eliminated_team_ids == ()
    assert result.incoming_gulag_team_ids == (18, 17)


def test_week_two_eliminates_current_gulag_low_and_selects_new_bottom_two() -> None:
    result = adjudicate(state(week=2, active=range(1, 19), gulag=(17, 18)), scores_for_week_two())
    assert result.eliminated_team_ids == (18,)
    assert set(result.incoming_gulag_team_ids).isdisjoint({17, 18})


def test_week_twelve_eliminates_gulag_low_and_general_pool_low() -> None:
    result = adjudicate(state(week=12, active=range(1, 9), gulag=(7, 8)), scores_for_week_twelve())
    assert result.eliminated_team_ids == (8, 6)
    assert result.incoming_gulag_team_ids == ()


@pytest.mark.parametrize("week", [13, 14, 15, 16])
def test_late_week_directly_cuts_lowest_team(week: int) -> None:
    result = adjudicate(state(week=week, active=(1, 2, 3)), scores((1, 90), (2, 80), (3, 70)))
    assert result.eliminated_team_ids == (3,)


def test_week_seventeen_names_high_score_champion() -> None:
    result = adjudicate(state(week=17, active=(1, 2)), scores((1, 101), (2, 99)))
    assert result.champion_team_id == 1
```

- [ ] **Step 2: Run tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/adjudication/test_engine.py -v`

- [ ] **Step 3: Implement explicit phase dispatch**

`phase_for_week()` returns `GULAG_ENTRY`, `GULAG_CYCLE`, `DOUBLE_ELIMINATION`, `DIRECT_CUT`, or `CHAMPIONSHIP`. Implement one pure function per phase. All functions validate expected active-team count from the schedule and return `unresolved` for a tie at a decision boundary.

- [ ] **Step 4: Add invariants**

Assert eliminated and incoming gulag sets are disjoint, eliminated teams were active, current gulag teams cannot become incoming gulag, survivors equal active minus eliminated, and the expected end-player count matches the rules schedule.

- [ ] **Step 5: Verify and commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation/src/ultimate_guillotine/adjudication packages/league-automation/tests/adjudication
git commit -m "feat: encode guillotine season state machine"
```

### Task 3: Structured overrides, insurance, and substitutions

**Files:**
- Create through CLI: `supabase/migrations/<generated>_adjudication_overrides.sql`
- Create: `packages/league-automation/src/ultimate_guillotine/adjudication/overrides.py`
- Create: `packages/league-automation/tests/adjudication/test_overrides.py`
- Create: `supabase/tests/adjudication_overrides.sql`

**Interfaces:**
- Consumes: accepted `LeagueOverride` events.
- Produces: `apply_overrides(state, overrides) -> WeekState`.

- [ ] **Step 1: Write failing override tests**

```python
def test_insurance_substitution_changes_gulag_participant_but_preserves_qualifier() -> None:
    updated = apply_overrides(
        state(week=5, gulag=(1, 2)),
        [insurance_override(qualified_team_id=1, substitute_team_id=3, contract_id=9)],
    )
    assert updated.current_gulag_team_ids == (3, 2)
    assert updated.gulag_qualification_team_ids == (1, 2)


def test_conflicting_substitutions_are_unresolved() -> None:
    with pytest.raises(OverrideConflict):
        apply_overrides(state(week=5, gulag=(1, 2)), conflicting_overrides())
```

- [ ] **Step 2: Run tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/adjudication/test_overrides.py -v`

- [ ] **Step 3: Create override migration**

Run: `supabase migration new adjudication_overrides`. Create `private.league_overrides` with season/week, override type, affected team, substitute team, contract/trade reference, source event, actor member, reason, accepted time, and immutable payload. Add check constraints for required fields by override type and a unique idempotency key.

Grant `automation_worker` select, insert, and update on `private.league_overrides` plus usage/select on its sequence; grant no delete.

- [ ] **Step 4: Implement pure override application**

Support `score_override`, `gulag_substitution`, `insurance_exercise`, and `eligibility_override`. Reject duplicate substitutes, eliminated substitutes, wrong season/week, and conflicting operations. Preserve original qualification in the output audit fields.

- [ ] **Step 5: Verify and commit**

Run: `supabase db reset && supabase test db && pnpm test:agents`

```bash
git add supabase packages/league-automation/src/ultimate_guillotine/adjudication packages/league-automation/tests/adjudication
git commit -m "feat: support audited adjudication overrides"
```

### Task 4: Persist weekly state versions and corrections

**Files:**
- Create through CLI: `supabase/migrations/<generated>_weekly_state_versions.sql`
- Create: `packages/league-automation/src/ultimate_guillotine/adjudication/repository.py`
- Create: `packages/league-automation/tests/adjudication/test_repository.py`
- Create: `supabase/tests/weekly_state_versions.sql`

**Interfaces:**
- Consumes: `AdjudicationResult` and source input hash.
- Produces: `AdjudicationRepository.save(result) -> SavedAdjudication` with `provisional`, `final`, `unresolved`, or `corrected`.

- [ ] **Step 1: Write failing version tests**

```python
async def test_same_input_hash_reuses_state_version(repository) -> None:
    first = await repository.save(result(input_hash="abc"))
    second = await repository.save(result(input_hash="abc"))
    assert first.id == second.id


async def test_material_change_after_final_creates_correction(repository) -> None:
    final = await repository.save(final_result(eliminated=(8,), input_hash="a"))
    corrected = await repository.save(final_result(eliminated=(7,), input_hash="b"))
    assert corrected.status == "corrected"
    assert corrected.corrects_state_id == final.id
```

- [ ] **Step 2: Create migration and repository**

Run `supabase migration new weekly_state_versions`. Create `private.weekly_state_versions`, `private.weekly_team_results`, and their foreign-key indexes. Unique keys cover `(season_id, week, input_hash)` and one current final version per season/week using a partial unique index. Corrections reference the prior final state.

Grant `automation_worker` select, insert, and update on both new tables plus usage/select on their sequences; grant no delete.

Repository writes state, team results, and immutable league events in one transaction. Cosmetic point changes without material rank/outcome change create a new source snapshot but not a league correction event.

- [ ] **Step 3: Verify and commit**

Run: `supabase db reset && supabase test db && pnpm test:agents`

```bash
git add supabase packages/league-automation/src/ultimate_guillotine/adjudication packages/league-automation/tests/adjudication
git commit -m "feat: version weekly adjudication results"
```

### Task 5: Stabilization scheduler, renderer, and worker handler

**Files:**
- Create: `agents/weekly-adjudicator/runner.py`
- Create: `packages/league-automation/src/ultimate_guillotine/adjudication/stabilize.py`
- Create: `packages/league-automation/src/ultimate_guillotine/adjudication/render.py`
- Create: `packages/league-automation/tests/adjudication/test_runner.py`
- Create through CLI: `supabase/migrations/<generated>_adjudication_cron.sql`
- Modify: `services/mac-worker/main.py`

**Interfaces:**
- Consumes: jobs `adjudication.provisional`, `adjudication.finalize`, `adjudication.correction_check`.
- Produces: state version plus signed public or commissioner-only message.

- [ ] **Step 1: Write failing stabilization tests**

```python
def test_two_identical_fresh_snapshots_are_stable() -> None:
    assert is_stable(snapshot("a", fetched_at=tuesday(9, 0)), snapshot("a", fetched_at=tuesday(9, 10)))


def test_unresolved_result_routes_only_to_commissioner(runner, delivery) -> None:
    await runner.handle(unresolved_job())
    assert delivery.reservations[0].target_kind == "commissioner"
```

- [ ] **Step 2: Implement runner and deterministic messages**

Provisional output states danger and explicitly says provisional. Final output names eliminated/cut team, surviving gulag team, incoming gulag entrants, score margins, and next CT deadline. Correction output names old and new outcomes plus the corrected source fact.

- [ ] **Step 3: Schedule jobs centrally**

Run `supabase migration new adjudication_cron`. Use `cron.schedule` functions, never direct writes to `cron.job`. Schedule a frequent lightweight enqueue check during the NFL week; the check reads Sleeper/NFL schedule state already synchronized and enqueues only when a game window or Tuesday stabilization gate is due. Unique job idempotency keys prevent repeated cron ticks from posting.

- [ ] **Step 4: Register handlers and verify**

Run: `supabase db reset && supabase test db && pnpm test:agents && pnpm lint:agents`

- [ ] **Step 5: Commit**

```bash
git add agents/weekly-adjudicator supabase services/mac-worker/main.py packages/league-automation/src/ultimate_guillotine/adjudication packages/league-automation/tests/adjudication
git commit -m "feat: automate weekly adjudication"
```

### Task 6: Full-season simulation and production gate

**Files:**
- Create: `scripts/simulate_season.py`
- Create: `packages/league-automation/tests/adjudication/test_full_season.py`
- Create: `packages/league-automation/tests/fixtures/adjudication/season_2026.json`
- Create: `docs/runbooks/weekly-adjudicator.md`

**Interfaces:**
- Consumes: literal 17-week synthetic score fixture.
- Produces: replayable transition report from 18 teams to one champion.

- [ ] **Step 1: Build the literal fixture and expected transition list**

Include 18 initial teams, every weekly score, current gulag participants, one substitution, one exact tie/unresolved rerun, one material correction, and literal expected survivors after each week.

- [ ] **Step 2: Write and run the full-season test**

Assert 18 starters, 17 final transitions, week-12 double elimination, direct cuts in weeks 13–16, exactly one champion, and no duplicate event IDs after processing the season twice.

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/adjudication/test_full_season.py -v`

- [ ] **Step 3: Shadow historical weeks and self-test output**

Run the simulator against retained historical sheet layouts without publishing. Send provisional, final, unresolved, and correction fixtures to the self-test chat and verify target routing.

- [ ] **Step 4: Run all gates and enable production**

Run: `pnpm test:agents && pnpm lint:agents && supabase test db && python3 scripts/mac-mini/doctor.py`

Enable Weekly Adjudicator production mode only after the simulation and self-test pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/simulate_season.py packages/league-automation/tests/adjudication packages/league-automation/tests/fixtures/adjudication docs/runbooks/weekly-adjudicator.md
git commit -m "test: qualify Weekly Adjudicator for production"
```
