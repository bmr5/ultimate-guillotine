# Weekly Storyteller Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and automatically publish an entertaining weekly recap whose every factual claim is traceable to finalized league data.

**Architecture:** A deterministic fact-packet builder joins finalized state, trades, survival snapshots, records, and prefiltered chat candidates. OpenAI writes copy from that closed packet; a deterministic claim validator rejects unsupported facts and falls back to a template.

**Tech Stack:** Foundation Python package, OpenAI Python 3.5.0 Responses API, Pydantic Structured Outputs, PostgreSQL, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-weekly-storyteller-agent-design.md`

## Global Constraints

- Complete foundation, Trade Registrar, Weekly Adjudicator, and Game Pulse factual layers first.
- Run only from a newly finalized weekly state.
- Do not invent scores, ranks, quotes, trades, amounts, motivations, records, or historical comparisons.
- Direct quotes require an exact retained source excerpt.
- Unsupported sections are omitted.
- A second factual-validation failure uses the deterministic fallback.
- Use OpenAI Responses with `store=False`; keep stable instructions before dynamic facts.

---

### Task 1: Build the closed weekly fact packet

**Files:**
- Create: `agents/weekly-storyteller/agent.yaml`
- Create: `packages/league-automation/src/ultimate_guillotine/story/models.py`
- Create: `packages/league-automation/src/ultimate_guillotine/story/facts.py`
- Create: `packages/league-automation/tests/story/test_facts.py`

**Interfaces:**
- Consumes: finalized weekly state ID and repositories for scores, trades, pulse, history, chat candidates.
- Produces: `WeeklyFactPacket` and SHA-256 `facts_hash`.

- [ ] **Step 1: Write failing packet tests**

```python
async def test_packet_contains_only_selected_week(repository) -> None:
    packet = await build_fact_packet(repository, season=2026, week=4, state_id=22)
    assert all(trade.week == 4 for trade in packet.trades)
    assert packet.final_state_id == 22


async def test_packet_excludes_private_member_fields(repository) -> None:
    payload = (await build_fact_packet(repository, 2026, 4, 22)).model_dump()
    serialized = json.dumps(payload)
    assert "phone" not in serialized
    assert "email" not in serialized
    assert "dues" not in serialized
```

- [ ] **Step 2: Run tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/story/test_facts.py -v`

- [ ] **Step 3: Implement packet models and query builder**

The packet has final ranks/scores, elimination/cut, surviving and incoming gulag teams, closest escape, largest movement, accepted trade revisions, FAAB obligations, pulse snapshots, supported historical records, chat candidates, next phase, and CT deadlines. Every fact includes source table and source row/event ID.

```yaml
name: weekly-storyteller
job_type: weekly-storyteller.run
delivery_modes: [disabled, test, production]
prompt_version: "2026.1"
fallback_template_version: "2026.1"
```

- [ ] **Step 4: Verify and commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add agents/weekly-storyteller packages/league-automation/src/ultimate_guillotine/story packages/league-automation/tests/story
git commit -m "feat: assemble weekly recap facts"
```

### Task 2: Prefilter and retain auditable chat highlights

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/story/highlights.py`
- Create: `packages/league-automation/tests/story/test_highlights.py`

**Interfaces:**
- Consumes: allowlisted weekly `MessageEnvelope` metadata and text from the Mac Messages reader.
- Produces: `ChatHighlightCandidate` values with source GUID, relevance reasons, exact excerpt, and reactions/replies.

- [ ] **Step 1: Write failing privacy and relevance tests**

```python
def test_prefilter_selects_reacted_league_message() -> None:
    candidates = prefilter_highlights([reacted_message("Max escaped by 0.2")])
    assert candidates[0].reasons == ("reaction", "league_term")


def test_prefilter_drops_unrelated_personal_message() -> None:
    assert prefilter_highlights([plain_message("my flight lands at 6")]) == []
```

- [ ] **Step 2: Implement deterministic prefilter**

Select messages with reactions, replies, trade alerts, bot interaction, player/team names, score/gulag/cut language, or commissioner markers. Normalize excerpts to a bounded length and redact recognized phone/email patterns before persistence or model input. Do not upload the rest of the chat.

- [ ] **Step 3: Verify and commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation/src/ultimate_guillotine/story/highlights.py packages/league-automation/tests/story/test_highlights.py
git commit -m "feat: select private-safe recap highlights"
```

### Task 3: Generate structured recap copy and deterministic fallback

**Files:**
- Create: `agents/weekly-storyteller/prompt.md`
- Create: `packages/league-automation/src/ultimate_guillotine/story/generate.py`
- Create: `packages/league-automation/src/ultimate_guillotine/story/fallback.py`
- Create: `packages/league-automation/tests/story/test_generate.py`

**Interfaces:**
- Consumes: `WeeklyFactPacket`, shared `StructuredOutputClient`.
- Produces: `RecapDraft` with sections and `ClaimReference` records.

- [ ] **Step 1: Write failing generation tests with a fake AI**

```python
async def test_no_trade_week_omits_trade_section(fake_ai) -> None:
    draft = await generate_recap(packet(trades=[]), fake_ai)
    assert "Trades" not in [section.heading for section in draft.sections]


def test_fallback_uses_literal_packet_values() -> None:
    body = render_fallback(packet(eliminated_name="Team 8", eliminated_score="71.4"))
    assert "Team 8" in body
    assert "71.4" in body
```

- [ ] **Step 2: Run tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/story/test_generate.py -v`

- [ ] **Step 3: Implement prompt and structured response**

The response schema requires headline, one-sentence summary, ordered sections, and for each factual sentence a list of fact IDs. Instructions permit playful tone but prohibit new proper nouns, numbers, quotes, or motivations not in the packet. Set `text.verbosity="low"`, `store=False`, and a stable `prompt_cache_key` per prompt version.

- [ ] **Step 4: Implement fallback**

The deterministic template renders supported sections directly from packet fields and never calls AI. It includes result, incoming gulag, closest escape, accepted trades, next phase, and signature when present.

- [ ] **Step 5: Verify and commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add agents/weekly-storyteller/prompt.md packages/league-automation/src/ultimate_guillotine/story packages/league-automation/tests/story
git commit -m "feat: draft grounded weekly recaps"
```

### Task 4: Validate every generated factual claim

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/story/validate.py`
- Create: `packages/league-automation/tests/story/test_validate.py`

**Interfaces:**
- Consumes: `RecapDraft`, `WeeklyFactPacket`.
- Produces: `ValidationReport` with supported/unsupported claim IDs.

- [ ] **Step 1: Write mutation-style failing tests**

```python
def test_validator_rejects_changed_score() -> None:
    report = validate_draft(draft_claiming_score("72.4"), packet(actual_score="71.4"))
    assert report.valid is False
    assert report.errors[0].code == "unsupported_number"


def test_validator_rejects_quote_without_source_excerpt() -> None:
    report = validate_draft(draft_with_quote("I am cooked"), packet(chat_candidates=[]))
    assert report.valid is False
```

- [ ] **Step 2: Implement validation**

Build allowed normalized sets for member/team/player names, numbers, amounts, weeks, trade IDs, and exact quotes. Validate structured claim references and scan rendered text for new numbers/proper nouns. One failure triggers one fresh generation with the error list; a second failure returns fallback.

- [ ] **Step 3: Verify and commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation/src/ultimate_guillotine/story/validate.py packages/league-automation/tests/story/test_validate.py
git commit -m "feat: validate recap factual claims"
```

### Task 5: Persist, deliver, correct, and qualify the recap

**Files:**
- Create: `agents/weekly-storyteller/runner.py`
- Create: `packages/league-automation/src/ultimate_guillotine/story/repository.py`
- Create: `packages/league-automation/tests/story/test_runner.py`
- Create: `packages/league-automation/tests/fixtures/story/weekly_packets.json`
- Create: `docs/runbooks/weekly-storyteller.md`
- Modify: `services/mac-worker/main.py`

**Interfaces:**
- Consumes: `weekly-storyteller.run` and `weekly-storyteller.correction` jobs.
- Produces: versioned `recaps` row and one signed outbound recap/correction.

- [ ] **Step 1: Write failing run identity and correction tests**

```python
async def test_same_state_prompt_and_facts_publish_once(runner, delivery) -> None:
    await runner.handle(recap_job(state=22, prompt="2026.1", facts="abc"))
    await runner.handle(recap_job(state=22, prompt="2026.1", facts="abc"))
    assert len(delivery.reservations) == 1


async def test_cosmetic_score_correction_does_not_resend_full_recap(runner, delivery) -> None:
    await runner.handle(correction_job(material=False))
    assert delivery.reservations == []
```

- [ ] **Step 2: Implement persistence and delivery**

The unique key is `(season_id, week, finalized_state_id, prompt_version, facts_hash)`. Store packet source IDs, draft, validation report, model response ID, and final body before reserving delivery. Split only when required by tested Messages limits, using one recap ID and numbered parts.

- [ ] **Step 3: Build evaluation fixtures and self-test**

Fixtures cover week one, ordinary gulag week, week-12 double elimination, direct cut, no trades, complex contracts, no chat candidates, historical record, hallucinated score, duplicate run, and material correction. Send AI and fallback variants to the self-test chat.

- [ ] **Step 4: Verify and enable production**

Run: `pnpm test:agents && pnpm lint:agents && supabase test db && python3 scripts/mac-mini/doctor.py`

Production requires two historical factual replays and one current shadow week with zero unsupported published claims.

- [ ] **Step 5: Commit**

```bash
git add agents/weekly-storyteller services/mac-worker/main.py packages/league-automation/src/ultimate_guillotine/story packages/league-automation/tests/story packages/league-automation/tests/fixtures/story docs/runbooks/weekly-storyteller.md
git commit -m "test: qualify Weekly Storyteller for production"
```

