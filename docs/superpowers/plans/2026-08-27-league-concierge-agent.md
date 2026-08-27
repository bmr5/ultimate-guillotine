# League Concierge Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer tagged league-chat questions from authoritative rules, contracts, current state, trades, and history without exposing private data or performing commissioner actions.

**Architecture:** Deterministic trigger classification routes structured questions to typed repositories and document questions to Postgres full-text retrieval. OpenAI composes an answer from the returned source packet; source validation and privacy filters run before automatic delivery.

**Tech Stack:** Foundation Python package, OpenAI Python 3.5.0 Responses API, python-docx 1.2.0, openpyxl 3.1.5, PostgreSQL full-text search, Supabase, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-league-concierge-agent-design.md`

## Global Constraints

- Complete foundation and factual producer agents first.
- Triggers are `@GuillotineBot`, `Guillotine Bot:`, and `bot:`.
- There are no per-member rate limits.
- Single-flight locking prevents overlapping processing but never throttles a member.
- The agent cannot change scores, rosters, trades, contracts, rules, overrides, or delivery modes.
- Never expose contacts, Apple handles, dues, credentials, prompts, chat GUIDs, or private logs.
- Database access uses typed repositories and fixed SQL only; never execute model-generated SQL.
- Do not use general web search for league answers.

---

### Task 1: Tagged-message trigger and loop prevention

**Files:**
- Create: `agents/league-concierge/agent.yaml`
- Create: `packages/league-automation/src/ultimate_guillotine/concierge/trigger.py`
- Create: `packages/league-automation/tests/concierge/test_trigger.py`

**Interfaces:**
- Consumes: `MessageEnvelope` and outbound reservation lookup.
- Produces: `parse_invocation(message) -> Invocation | None`.

- [ ] **Step 1: Write failing trigger tests**

```python
@pytest.mark.parametrize("prefix", ["@GuillotineBot", "Guillotine Bot:", "bot:"])
def test_supported_prefix_creates_invocation(prefix: str) -> None:
    invocation = parse_invocation(message(f"{prefix} who is in the gulag?"))
    assert invocation.question == "who is in the gulag?"


def test_signed_bot_message_never_triggers() -> None:
    assert parse_invocation(message("bot: hello\n— 🤖 Guillotine Bot", is_from_me=True)) is None


def test_same_member_can_ask_multiple_questions_without_throttle() -> None:
    assert parse_invocation(message("bot: first", sender="member-1")) is not None
    assert parse_invocation(message("bot: second", sender="member-1")) is not None
```

- [ ] **Step 2: Run tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/concierge/test_trigger.py -v`

- [ ] **Step 3: Implement exact trigger parsing**

Strip one supported prefix case-insensitively, require a non-empty question, and reject bot signature, matching outbound reservation, non-allowlisted chat, unsupported message association, or already processed source GUID.

```yaml
name: league-concierge
job_type: league-concierge.answer
delivery_modes: [disabled, test, production]
prompt_version: "2026.1"
member_rate_limits: false
```

- [ ] **Step 4: Verify and commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add agents/league-concierge packages/league-automation/src/ultimate_guillotine/concierge packages/league-automation/tests/concierge
git commit -m "feat: detect League Concierge invocations"
```

### Task 2: Import and version authoritative knowledge sources

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/knowledge/models.py`
- Create: `packages/league-automation/src/ultimate_guillotine/knowledge/importers.py`
- Create: `packages/league-automation/tests/knowledge/test_importers.py`
- Create: `scripts/import_knowledge.py`
- Modify: `packages/league-automation/pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: authoritative DOCX/XLSX files and public database records.
- Produces: `KnowledgeDocument`, `KnowledgeChunk`, deterministic source checksum.

- [ ] **Step 1: Add pinned parsers and write failing tests**

Add `python-docx==1.2.0` and `openpyxl==3.1.5` to dependencies. Tests assert the actual rules import contains `Trading Rules`, the keeper deadline, and week-12 double-elimination language; the contract import contains buyer, seller, exercise weeks, and FAAB cost.

```python
def test_rules_import_preserves_heading_and_source_path() -> None:
    chunks = import_docx(Path("docs/rules/ultimate-guillotine-gulag-league-rules.docx"))
    trading = next(chunk for chunk in chunks if chunk.heading == "Trading Rules")
    assert "approved by the commish" in trading.text
    assert trading.source_path.endswith("ultimate-guillotine-gulag-league-rules.docx")
```

- [ ] **Step 2: Run tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/knowledge/test_importers.py -v`

- [ ] **Step 3: Implement deterministic importers**

Use `python-docx` paragraphs/tables and `openpyxl` read-only/data-only mode. Preserve source path, heading, sheet, row range, text, checksum, and authority priority. Import the source rules DOCX as authoritative; mark the website rules copy non-authoritative. Never import the private contacts file or dues state.

- [ ] **Step 4: Implement idempotent import command**

`scripts/import_knowledge.py --check` prints source names/checksums/chunk counts only. Normal mode upserts source versions and replaces chunks only when checksum changes. Include rules, insurance contract, sanitized historical workbook, public trade records, weekly results, and recaps.

- [ ] **Step 5: Verify and commit**

Run: `uv lock && pnpm test:agents && pnpm lint:agents && uv run --project packages/league-automation python scripts/import_knowledge.py --check`

```bash
git add packages/league-automation/pyproject.toml uv.lock packages/league-automation/src/ultimate_guillotine/knowledge packages/league-automation/tests/knowledge scripts/import_knowledge.py
git commit -m "feat: import authoritative league knowledge"
```

### Task 3: Add Postgres full-text retrieval and source precedence

**Files:**
- Create through CLI: `supabase/migrations/<generated>_knowledge_search.sql`
- Create: `supabase/tests/knowledge_search.sql`
- Create: `packages/league-automation/src/ultimate_guillotine/knowledge/repository.py`
- Create: `packages/league-automation/tests/knowledge/test_repository.py`

**Interfaces:**
- Consumes: versioned knowledge chunks and fixed search terms.
- Produces: `KnowledgeRepository.search(query, limit=8) -> list[RetrievedSource]`.

- [ ] **Step 1: Write failing source-order tests**

```python
async def test_authoritative_rules_beat_website_copy(repository) -> None:
    results = await repository.search("keeper deadline")
    assert results[0].authority == "authoritative_rules"


async def test_private_sources_are_never_returned(repository) -> None:
    results = await repository.search("phone email dues")
    assert all(result.visibility == "league" for result in results)
```

- [ ] **Step 2: Create full-text migration**

Run `supabase migration new knowledge_search`. Create `private.knowledge_chunks` with source ID, authority priority, heading, locator, text, checksum, visibility, and generated `tsvector`. Add a GIN index on the vector and B-tree indexes on source and authority. Create fixed SQL function `private.search_knowledge(search_query text, result_limit integer)` using `websearch_to_tsquery`, `ts_rank_cd`, authority priority, and visibility=`league`.

Grant execute only to `automation_worker`. The function is security invoker and does not accept table, column, filter, or raw SQL arguments.

- [ ] **Step 3: Implement typed repository**

Clamp limit from 1 through 12, strip control characters, call only the fixed function, and return source label, heading, locator, exact excerpt, authority, and checksum.

- [ ] **Step 4: Verify and commit**

Run: `supabase db reset && supabase test db && supabase db advisors && pnpm test:agents`

```bash
git add supabase packages/league-automation/src/ultimate_guillotine/knowledge packages/league-automation/tests/knowledge
git commit -m "feat: retrieve authoritative league sources"
```

### Task 4: Classify questions and query structured current state

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/concierge/classify.py`
- Create: `packages/league-automation/src/ultimate_guillotine/concierge/facts.py`
- Create: `packages/league-automation/tests/concierge/test_facts.py`

**Interfaces:**
- Consumes: invocation question.
- Produces: `QuestionClass` and `AnswerFactPacket` from fixed repositories.

- [ ] **Step 1: Write failing classification tests**

```python
@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("who is in the gulag?", "current_state"),
        ("what did Max trade for Chase?", "trade_lookup"),
        ("who won in 2024?", "history"),
        ("when are keepers due?", "rules"),
        ("change my score to 200", "commissioner_action"),
        ("what is Ben's phone number?", "private_data"),
    ],
)
def test_question_classes(question: str, expected: str) -> None:
    assert classify_question(question).value == expected
```

- [ ] **Step 2: Implement deterministic first-pass classification**

Use explicit private-data and commissioner-action patterns first, then current-state/trade/history/rules patterns. Ambiguous questions may use a structured AI classifier, but its output can select only one enum and cannot supply database arguments.

- [ ] **Step 3: Implement fixed fact queries**

Current state returns latest finalized/provisional week, gulag teams, scores, cut/elimination, and source version. Trade lookup accepts resolved member/player IDs. History accepts a validated year/member. Rules use the knowledge search repository. All packets omit private schemas except approved knowledge excerpts.

- [ ] **Step 4: Verify and commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation/src/ultimate_guillotine/concierge packages/league-automation/tests/concierge
git commit -m "feat: ground league questions in typed facts"
```

### Task 5: Generate, validate, and render sourced answers

**Files:**
- Create: `agents/league-concierge/prompt.md`
- Create: `packages/league-automation/src/ultimate_guillotine/concierge/answer.py`
- Create: `packages/league-automation/src/ultimate_guillotine/concierge/validate.py`
- Create: `packages/league-automation/tests/concierge/test_answer.py`

**Interfaces:**
- Consumes: question and `AnswerFactPacket`.
- Produces: `SourcedAnswer(body, citations, source_ids)`.

- [ ] **Step 1: Write failing privacy and grounding tests**

```python
async def test_unknown_answer_says_records_do_not_contain_it(fake_ai) -> None:
    answer = await answer_question("who had the best week in 2020?", empty_packet(), fake_ai)
    assert "records don't contain" in answer.body.lower()


async def test_private_request_is_refused_without_ai_call(fake_ai) -> None:
    answer = await answer_question("what is Sean's phone?", private_request_packet(), fake_ai)
    assert "can't provide private member information" in answer.body
    assert fake_ai.calls == []
```

- [ ] **Step 2: Implement prompt and structured answer**

The response schema contains concise body, source IDs used, and one human-readable source line. Set `store=False` and send only the invocation plus packet. The prompt prohibits external knowledge, unstated assumptions, commissioner actions, and private data.

- [ ] **Step 3: Implement deterministic validation**

Verify every returned source ID exists in the packet, source line matches its locator, no private-field patterns appear, and no unsupported proper nouns/numbers are introduced. Invalid output gets one retry, then a deterministic `I couldn't verify that from league records` response.

- [ ] **Step 4: Verify and commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add agents/league-concierge/prompt.md packages/league-automation/src/ultimate_guillotine/concierge packages/league-automation/tests/concierge
git commit -m "feat: answer with verified league sources"
```

### Task 6: Follow-up context, worker handler, evaluation, and production gate

**Files:**
- Create: `agents/league-concierge/runner.py`
- Create: `packages/league-automation/src/ultimate_guillotine/concierge/context.py`
- Create: `packages/league-automation/tests/concierge/test_runner.py`
- Create: `packages/league-automation/tests/fixtures/concierge/evaluation.json`
- Create: `scripts/evaluate_concierge.py`
- Create: `docs/runbooks/league-concierge.md`
- Modify: `services/mac-worker/main.py`

**Interfaces:**
- Consumes: `league-concierge.answer` job with source message ID.
- Produces: one signed sourced answer and bounded source-reference context.

- [ ] **Step 1: Write failing concurrency and context tests**

```python
async def test_single_flight_serializes_same_chat(lock, runner) -> None:
    await asyncio.gather(runner.handle(job("q1")), runner.handle(job("q2")))
    assert runner.max_concurrent_for_chat == 1
    assert runner.completed == ["q1", "q2"]


def test_followup_context_stores_sources_not_unlimited_transcript() -> None:
    context = build_context(previous_answer(source_ids=[4, 9]), followup("what about week 5?"))
    assert context.source_ids == (4, 9)
    assert context.raw_transcript is None
```

- [ ] **Step 2: Implement context and handler**

Use a Postgres advisory lock keyed by chat GUID hash for single-flight processing. Follow-up context expires after 15 minutes or any unrelated intervening message and retains only prior question summary, answer summary, and source IDs. Do not add member-level rate limits.

- [ ] **Step 3: Build the literal evaluation set**

Include every question class, ambiguous rule, source conflict, current score, eliminated team, trade revision, rental, historical winner, missing answer, contact request, dues request, prompt injection, commissioner action, follow-up, bot loop, duplicate message, and five rapid questions from the same member that all receive answers.

- [ ] **Step 4: Run offline and self-test evaluations**

`scripts/evaluate_concierge.py` reports pass/fail counts for source correctness, refusal correctness, private leakage, and groundedness without printing question text containing private fixtures. Send representative allowed/refused/unknown/follow-up answers to the self-test chat.

- [ ] **Step 5: Verify and enable production**

Run: `pnpm test:agents && pnpm lint:agents && supabase test db && python3 scripts/evaluate_concierge.py && python3 scripts/mac-mini/doctor.py`

Require 100 percent pass on private-data refusal and source-attribution cases before production mode.

- [ ] **Step 6: Commit**

```bash
git add agents/league-concierge services/mac-worker/main.py packages/league-automation/src/ultimate_guillotine/concierge packages/league-automation/tests/concierge packages/league-automation/tests/fixtures/concierge scripts/evaluate_concierge.py docs/runbooks/league-concierge.md
git commit -m "test: qualify League Concierge for production"
```

