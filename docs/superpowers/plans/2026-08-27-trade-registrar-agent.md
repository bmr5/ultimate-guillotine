# Trade Registrar Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect official 🚨 trade announcements, validate and deduplicate their terms, persist revisions, and post automatic signed confirmations or clarification requests.

**Architecture:** The Mac message watcher enqueues qualifying source-message IDs. Deterministic candidate detection, alias resolution, validation, fingerprinting, and persistence surround one OpenAI Responses API structured extraction call; database constraints own idempotency.

**Tech Stack:** Foundation Python package, OpenAI Python 3.5.0 Responses API with Structured Outputs, Pydantic, PostgreSQL, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-trade-registrar-agent-design.md`

## Global Constraints

- Complete `docs/superpowers/plans/2026-08-27-automation-foundation.md` first.
- Require both `🚨` and recognizable trade language.
- Never infer missing consideration, party, unit, rental return condition, or special term.
- Preserve source evidence and every material revision.
- Exact duplicates create neither a second trade nor a second message.
- Use OpenAI Responses with `store=False` and JSON-schema Structured Outputs; default model is `gpt-5.5`, configurable by `OPENAI_MODEL`.
- Automatic delivery must pass the self-test target before production mode is enabled.

---

### Task 1: Candidate detection and trade domain models

**Files:**
- Create: `agents/trade-registrar/agent.yaml`
- Create: `packages/league-automation/src/ultimate_guillotine/trades/models.py`
- Create: `packages/league-automation/src/ultimate_guillotine/trades/detect.py`
- Create: `packages/league-automation/tests/trades/test_detect.py`

**Interfaces:**
- Consumes: `MessageEnvelope` from the foundation.
- Produces: `is_trade_candidate(message) -> bool`, `TradeProposal`, `TradeParty`, `TradeAsset`.

- [ ] **Step 1: Write failing candidate tests**

```python
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("🚨 Max sends Chase to Evan for DJ Moore + 450 FAAB", True),
        ("Max sends Chase to Evan for DJ Moore", False),
        ("🚨 huge game tonight", False),
        ("🚨 Ben rents Smith to Max for $5 with gulag protection", True),
    ],
)
def test_trade_candidate_requires_alert_and_terms(text: str, expected: bool) -> None:
    assert is_trade_candidate(message(text)) is expected
```

- [ ] **Step 2: Run the test red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/trades/test_detect.py -v`

- [ ] **Step 3: Implement deterministic detection and models**

Recognized terms are the case-insensitive words `send`, `receive`, `trade`, `buy`, `sell`, `rent`, `swap`, `faab`, `option`, and `protection`, including common inflections. `TradeProposal` contains `season`, `week`, `parties`, `assets`, `special_terms`, `effective_at`, `source_message_guid`, `confidence`, and `clarification_needed`. Amount assets require a unit enum of `faab`, `draft_dollars`, or `usd`; player assets use the Sleeper player ID after resolution.

```yaml
# agents/trade-registrar/agent.yaml
name: trade-registrar
job_type: trade.detect
delivery_modes: [disabled, test, production]
signature: "— 🤖 Guillotine Bot"
prompt_version: "2026.1"
```

- [ ] **Step 4: Verify and commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add agents/trade-registrar packages/league-automation/src/ultimate_guillotine/trades packages/league-automation/tests/trades
git commit -m "feat: detect official trade alerts"
```

### Task 2: Alias resolution and structured extraction

**Files:**
- Create: `agents/trade-registrar/prompt.md`
- Create: `packages/league-automation/src/ultimate_guillotine/ai/client.py`
- Create: `packages/league-automation/src/ultimate_guillotine/trades/aliases.py`
- Create: `packages/league-automation/src/ultimate_guillotine/trades/extract.py`
- Create: `packages/league-automation/tests/trades/test_extract.py`
- Modify: `packages/league-automation/pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: qualifying message text, active member aliases, Sleeper player directory.
- Produces: `StructuredOutputClient.parse(model, instructions, text, response_model)`, `extract_trade()`.

- [ ] **Step 1: Add the pinned SDK and write failing extraction tests**

Add `openai==3.5.0` to package dependencies and lock it. Test through a fake `StructuredOutputClient`, not the network:

```python
async def test_extract_preserves_units_and_rental_terms(fake_ai, aliases) -> None:
    proposal = await extract_trade(
        "🚨 Nick rents Tet McMillan from Sean for 92 FAAB down, 50 returned Monday",
        season=2026,
        week=2,
        aliases=aliases,
        ai=fake_ai,
    )
    assert proposal.assets[0].amount == 92
    assert proposal.assets[0].unit == "faab"
    assert proposal.special_terms == ["50 FAAB returned Monday"]


async def test_extract_marks_missing_counterparty_for_clarification(fake_ai, aliases) -> None:
    proposal = await extract_trade("🚨 Chase rented for 10", season=2026, week=2, aliases=aliases, ai=fake_ai)
    assert proposal.clarification_needed is True
```

- [ ] **Step 2: Run tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/trades/test_extract.py -v`

- [ ] **Step 3: Implement the OpenAI structured-output boundary**

The client calls `client.responses.parse(...)` with `store=False`, `model=settings.openai_model`, stable instructions first, dynamic message last, and the Pydantic response model. Persist the OpenAI response ID and token usage in `agent_runs`, but not hidden reasoning.

The prompt states: extract only explicit facts; use `null` for missing fields; never adjudicate fairness; preserve unusual terms verbatim; mark clarification when two recognized parties and one obligation are not present.

- [ ] **Step 4: Implement deterministic alias resolution**

Normalize Unicode, case, punctuation, and whitespace. Resolve league members from `members`, private aliases, and Sleeper display names. Resolve players against the current Sleeper player directory. Multiple matches remain unresolved; the model cannot choose between them.

- [ ] **Step 5: Verify and commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add agents/trade-registrar/prompt.md packages/league-automation/pyproject.toml uv.lock packages/league-automation/src/ultimate_guillotine/ai packages/league-automation/src/ultimate_guillotine/trades packages/league-automation/tests/trades
git commit -m "feat: extract structured trade terms"
```

### Task 3: Trade persistence, semantic fingerprints, and revisions

**Files:**
- Create through CLI: `supabase/migrations/<generated>_trade_assets_and_obligations.sql`
- Create: `supabase/tests/trade_idempotency.sql`
- Create: `packages/league-automation/src/ultimate_guillotine/trades/fingerprint.py`
- Create: `packages/league-automation/src/ultimate_guillotine/trades/repository.py`
- Create: `packages/league-automation/tests/trades/test_repository.py`

**Interfaces:**
- Consumes: validated `TradeProposal`.
- Produces: `trade_fingerprint(proposal)`, `TradeRepository.accept(proposal) -> TradeAcceptance` with status `created`, `duplicate`, or `revised`.

- [ ] **Step 1: Write failing fingerprint and repository tests**

```python
def test_fingerprint_ignores_party_and_asset_order() -> None:
    assert trade_fingerprint(proposal_a()) == trade_fingerprint(proposal_a_reordered())


async def test_same_trade_is_duplicate(repository) -> None:
    first = await repository.accept(proposal_a())
    second = await repository.accept(proposal_a_with_new_source_guid())
    assert first.status == "created"
    assert second.status == "duplicate"
    assert await repository.revision_count(first.trade_id) == 1
```

- [ ] **Step 2: Run tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/trades/test_repository.py -v`

- [ ] **Step 3: Create the migration through the CLI**

Run: `supabase migration new trade_assets_and_obligations`

Create `trade_parties`, `trade_assets`, and `trade_obligations`, each with identity primary key, indexed `trade_revision_id`, typed amount/unit constraints, and cascade delete only from a test transaction. Add `semantic_fingerprint text not null` to `trade_revisions` and a unique constraint on `(season_id, semantic_fingerprint)`. Add indexes for party/member, player ID, and effective week queries.

Enable RLS on all three tables, grant `anon`/`authenticated` select with explicit public-read policies, and grant `automation_worker` select, insert, and update plus usage/select on their sequences; grant no delete.

- [ ] **Step 4: Implement canonical fingerprint and atomic accept**

Canonical JSON sorts parties by stable member ID and assets by `(asset_type, player_id, amount, unit, from_member_id, to_member_id)`, preserves normalized special terms, and hashes UTF-8 JSON with SHA-256. `accept()` uses one transaction and `on conflict` rather than SELECT-then-INSERT.

A same-context proposal with changed canonical terms creates the next revision number and updates `trades.current_revision_id`. A rescission creates an event with `event_type='trade_rescinded'`; no row is erased.

- [ ] **Step 5: Add database idempotency assertions and verify**

The pgTAP test inserts the same fingerprint twice with `on conflict do nothing` and asserts one revision. Run: `supabase db reset && supabase test db && pnpm test:agents`

- [ ] **Step 6: Commit**

```bash
git add supabase packages/league-automation/src/ultimate_guillotine/trades packages/league-automation/tests/trades
git commit -m "feat: persist deduplicated trade revisions"
```

### Task 4: Agent runner, confirmations, and clarification flow

**Files:**
- Create: `agents/trade-registrar/runner.py`
- Create: `packages/league-automation/src/ultimate_guillotine/trades/render.py`
- Create: `packages/league-automation/tests/trades/test_runner.py`
- Modify: `services/mac-worker/main.py`

**Interfaces:**
- Consumes: queued job `{agent_name: "trade-registrar", source_message_id}`.
- Produces: accepted trade event and one reserved confirmation/clarification message.

- [ ] **Step 1: Write failing runner tests**

```python
async def test_duplicate_trade_sends_nothing(runner, duplicate_repository, delivery) -> None:
    result = await runner.handle(job_for("message-1"))
    assert result.status == "duplicate"
    assert delivery.reservations == []


async def test_ambiguous_trade_requests_clarification(runner, ambiguous_ai, delivery) -> None:
    await runner.handle(job_for("message-2"))
    assert "clarify" in delivery.reservations[0].body.lower()
    assert delivery.reservations[0].body.endswith("— 🤖 Guillotine Bot")
```

- [ ] **Step 2: Run tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/trades/test_runner.py -v`

- [ ] **Step 3: Implement renderer and runner**

Created confirmations include trade ID, sides, explicit amounts/units, week, permanence/rental summary, and signature. Revised confirmations start `🚨 Trade <id> updated`. Clarification messages quote only the minimum ambiguous phrase and ask one direct question.

Register the handler under both `trade.detect` and `trade.clarification` job types. Clarification replies must reference the source message or trade candidate ID before they can resume acceptance.

- [ ] **Step 4: Verify and commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add agents/trade-registrar services/mac-worker/main.py packages/league-automation/src/ultimate_guillotine/trades packages/league-automation/tests/trades
git commit -m "feat: run Trade Registrar automatically"
```

### Task 5: Historical replay and production gate

**Files:**
- Create: `scripts/replay_trade_history.py`
- Create: `packages/league-automation/tests/fixtures/trades/2025_contracts.json`
- Create: `packages/league-automation/tests/integration/test_trade_replay.py`
- Create: `docs/runbooks/trade-registrar.md`

**Interfaces:**
- Consumes: sanitized JSON fixtures derived from `history/contracts/2025-26/all-contracts.xlsx`.
- Produces: replay report and documented promotion procedure.

- [ ] **Step 1: Create fixture categories without personal contact data**

Include permanent sale, FAAB trade, one-week rental, deposit/return rental, option contract, no-trade payment, duplicate repost, amendment, rescission, and ambiguous alert. Each fixture has literal expected parties, amounts, units, and terms.

- [ ] **Step 2: Write and run replay tests**

The integration test processes every fixture twice and asserts accepted trade count, revision count, clarification count, and outbound count remain unchanged on the second pass.

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/integration/test_trade_replay.py -v`

- [ ] **Step 3: Exercise test-chat crash reconciliation**

Send one fixture to the self-test chat, stop the worker immediately after AppleScript returns, restart it, and verify the sent-message reconciliation marks one delivery without a duplicate.

- [ ] **Step 4: Run all gates and enable production for this agent only**

Run:

```bash
pnpm test:agents
pnpm lint:agents
supabase test db
python3 scripts/mac-mini/doctor.py
```

Set only Trade Registrar to `production`; all other agents remain `disabled` or `test`.

- [ ] **Step 5: Commit**

```bash
git add scripts/replay_trade_history.py packages/league-automation/tests/fixtures/trades packages/league-automation/tests/integration/test_trade_replay.py docs/runbooks/trade-registrar.md
git commit -m "test: qualify Trade Registrar for production"
```
