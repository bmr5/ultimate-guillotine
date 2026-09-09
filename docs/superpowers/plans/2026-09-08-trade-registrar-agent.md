# Trade Registrar Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect official 🚨 trade announcements in the allowlisted iMessage chat, extract and validate their terms, persist deduplicated trade revisions in Supabase, and post a signed confirmation or clarification request through the existing delivery layer.

**Architecture:** A deterministic trigger in the existing webhook listener hands qualifying messages to a `TradeRegistrar` handler. The handler makes exactly one structured-output call to OpenRouter (the only language-model step), resolves names deterministically against members, private aliases, and a Sleeper player directory, validates, fingerprints, and writes through a `TradeRepository` whose database constraints own idempotency. Every league-facing message goes through `DeliveryService`. A daily Hermes cron job keeps the player directory fresh.

**Tech Stack:** Python 3.12, Pydantic 2.13.5, httpx 0.28.1 with respx 0.23.1 for tests, psycopg 3.3.5, OpenRouter chat completions with `response_format: json_schema` (verified 2026-09-08), Sleeper `GET /v1/players/nfl`, Supabase migrations with pgTAP, Hermes cron on the `guillotine` profile.

**Spec:** `docs/superpowers/specs/2026-08-27-trade-registrar-agent-design.md`, which inherits `docs/superpowers/specs/2026-08-27-automation-foundation-design.md` (revision 2026-09-08).

## Global Constraints

- A message is a trade candidate only when it contains the red alert emoji `🚨` **and** trade language (`send`, `receive`, `trade`, `buy`, `sell`, `rent`, `swap`, `faab`, `option`, `protection`, `pays`, `insurance`, with common inflections). Detection is deterministic code in the listener, never a model.
- The language model extracts terms only. It never resolves ambiguity, never picks between two matching names, never decides fairness. Deterministic code resolves names, validates, fingerprints, and persists.
- Validation requires at least two recognized parties and one explicit asset or obligation; amounts keep their unit (`faab`, `draft_dollars`, `usd`); a rental keeps its return condition; unusual terms go verbatim into `special_terms`.
- Ambiguity produces a clarification request, never a logged trade.
- Three independent dedupe identities: Apple message GUID (already enforced by `private.webhook_receipts` and `private.source_messages.source_guid`), normalized message fingerprint (`private.source_messages` composite key), and the semantic trade fingerprint (new unique index in this plan). An exact semantic duplicate sends nothing. A materially different alert in the same trade context creates a new `trade_revisions` row and posts `Trade updated`.
- Rescission requires an explicit 🚨 announcement containing `rescind`, `rescinded`, `cancel`, `cancelled`, `void`, or `voided` naming the trade code or the same parties and player; it creates a `trade_rescinded` league event and never deletes rows.
- `DeliveryService.deliver` is the only path to the chat. Test mode reaches only the self-test chat; production only the league chat. Every bot message ends with `— 🤖 Guillotine Bot` (applied by `sign()` inside the delivery layer; never add it in agent code).
- Never log or print chat GUIDs, phone numbers, message bodies, or the OpenRouter key. Excerpts persisted for evidence are capped at 2000 characters and stored only in `private.source_messages` and `trade_revisions.terms.evidence_excerpt`.
- Prompts are versioned in the repository. `prompt_version` is `2026.1` and is recorded in `private.agent_runs.input_version` together with the model id.
- Model provider is OpenRouter. Default extraction model is `openai/gpt-5-mini` (structured outputs supported, $0.25/M input). The model id is configurable through `TRADE_EXTRACTION_MODEL`.
- `automation_worker` gains no DELETE grant. New public tables get RLS, select-only policies for `anon`/`authenticated`, and an `Automation writes <table>` policy for `automation_worker`, matching the existing migrations.
- All commands run from the repository root with `uv run --project packages/league-automation ...`; `pnpm test:agents` and `pnpm lint:agents` are the suite commands; DB-backed tests use the shared `conn` fixture in `packages/league-automation/tests/conftest.py` (skips without `TEST_DATABASE_URL`, rolls back). Follow TDD. Keep lines at or under 100 characters.
- Commit after each task with a conventional message ending in `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Verified External Interfaces

OpenRouter (read from the docs on 2026-09-08):

- `POST https://openrouter.ai/api/v1/chat/completions` with header `Authorization: Bearer <key>`.
- Body: `{"model": "...", "messages": [{"role": "system", ...}, {"role": "user", ...}], "response_format": {"type": "json_schema", "json_schema": {"name": "...", "strict": true, "schema": {...}}}, "provider": {"require_parameters": true}}`.
- Response: `choices[0].message.content` is the JSON string; `usage.prompt_tokens` and `usage.completion_tokens` are present; `id` is the response id.

Sleeper: `GET https://api.sleeper.app/v1/players/nfl` returns a JSON object keyed by player id with `full_name`, `first_name`, `last_name`, `position`, `team`, `active`. It is about 5 MB and Sleeper asks for at most one fetch per day.

Existing repository interfaces this plan builds on (do not redefine):

- `ultimate_guillotine.listener.processing`: `Trigger(name, matches, handle)`, `TriggerRegistry.register`, `InboundProcessor`.
- `ultimate_guillotine.listener.run.build_processor(settings, conn, client, delivery, notifier)`: the registration point, marked by the comment `Agents from later plans register their triggers here`.
- `ultimate_guillotine.messages.bluebubbles.InboundMessage(guid, chat_guid, sender_address, text, is_from_me, is_group, sent_at)`.
- `ultimate_guillotine.messages.delivery.DeliveryService.deliver(run_id, agent, content) -> DeliveryResult(status, outbound_id, message_guid)`; raises `DeliveryDisabled` or `TargetMismatch`.
- `ultimate_guillotine.data.repositories.RunRepository.reserve(agent, trigger, idempotency_key, invoked_by=None) -> int | None`, `.finish(run_id, status, output_hash=None, error=None)`; `SourceMessageRepository`; `chat_guid_hash`.
- `ultimate_guillotine.ops.notify.HermesNotifier` with `.ops/.feed/.drafts/.alerts(text)`.
- `ultimate_guillotine.cli.deps.build_deps() -> Deps(settings, conn, client, notifier)`, `build_delivery(deps)`, `run_scheduled(conn, agent, now, action, trigger="cron", idempotency_key=None)`.
- `ultimate_guillotine.sleeper.client.SleeperClient(http)`; `ultimate_guillotine.sleeper.sync.sync_season`.

## File Structure

```text
packages/league-automation/src/ultimate_guillotine/
  config.py                          # + openrouter_api_key, trade_extraction_model, sleeper_players_ttl_hours
  ai/__init__.py
  ai/openrouter.py                   # StructuredOutputClient: one structured call, typed errors, usage
  sleeper/client.py                  # + get_players()
  sleeper/players.py                 # PlayerDirectory sync into public.players
  trades/__init__.py
  trades/models.py                   # ExtractedTrade (model output), TradeProposal (resolved), TradeAsset, TradeParty
  trades/detect.py                   # is_trade_candidate, is_rescission_candidate
  trades/fingerprint.py              # message_fingerprint, trade_fingerprint, trade_context_key
  trades/resolve.py                  # MemberResolver, PlayerResolver, resolve_extracted -> TradeProposal
  trades/extract.py                  # prompt loading, extract_trade(client, text, ...) -> ExtractedTrade
  trades/repository.py               # TradeRepository: accept, rescind, find_by_code, list_recent
  trades/format.py                   # confirmation, updated, rescinded, clarification texts
  trades/registrar.py                # TradeRegistrar.handle + trade_trigger()
  cli/trades.py                      # ug trades extract | replay | list | retry
  cli/sleeper.py                     # + ug sleeper players
agents/trade-registrar/prompt.md     # versioned system prompt (2026.1)
supabase/migrations/<ts>_players_and_trade_fingerprints.sql
supabase/tests/trades.sql
hermes/guillotine/cron.yaml          # + guillotine-players-sync (daily)
hermes/guillotine/scripts/guillotine_players_sync.sh.template
tests/ (mirrors src): ai/, trades/, sleeper/test_players.py, cli/test_trades.py
tests/fixtures/trades/alerts.json    # anonymized alert fixtures per spec category
tests/fixtures/sleeper/players_small.json
```

---

### Task 1: Settings, OpenRouter structured-output client

**Files:**
- Modify: `packages/league-automation/src/ultimate_guillotine/config.py`
- Create: `packages/league-automation/src/ultimate_guillotine/ai/__init__.py`
- Create: `packages/league-automation/src/ultimate_guillotine/ai/openrouter.py`
- Create: `packages/league-automation/tests/ai/__init__.py`
- Create: `packages/league-automation/tests/ai/test_openrouter.py`
- Modify: `.env.example`
- Modify: `packages/league-automation/tests/test_config.py`

**Interfaces:**
- Consumes: `Settings`, httpx, respx.
- Produces:
  - `Settings.openrouter_api_key: SecretStr | None = None`, `Settings.trade_extraction_model: str = "openai/gpt-5-mini"`, `Settings.sleeper_players_ttl_hours: int = 24`.
  - `class AIUnavailable(Exception)` and `class AIInvalidOutput(Exception)` in `ai/openrouter.py`.
  - `@dataclass(frozen=True) class AIUsage: response_id: str; prompt_tokens: int; completion_tokens: int; model: str`.
  - `StructuredOutputClient(api_key: str, model: str, http: httpx.Client, base_url="https://openrouter.ai/api/v1")` with `parse(system: str, user: str, schema: type[T], schema_name: str) -> tuple[T, AIUsage]` where `T` is a Pydantic `BaseModel` subclass.

- [ ] **Step 1: Write the failing tests**

```python
# packages/league-automation/tests/ai/test_openrouter.py
import json

import httpx
import pytest
import respx
from pydantic import BaseModel

from ultimate_guillotine.ai.openrouter import AIInvalidOutput, AIUnavailable, StructuredOutputClient

URL = "https://openrouter.ai/api/v1/chat/completions"


class Shape(BaseModel):
    name: str
    sides: int


def ok(content: str) -> httpx.Response:
    return httpx.Response(200, json={
        "id": "gen-1", "model": "openai/gpt-5-mini",
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7},
    })


@respx.mock
def test_parse_sends_schema_and_returns_model_and_usage() -> None:
    route = respx.post(URL).mock(return_value=ok(json.dumps({"name": "square", "sides": 4})))
    client = StructuredOutputClient("key", "openai/gpt-5-mini", httpx.Client())
    shape, usage = client.parse("sys", "user text", Shape, "shape")
    assert shape == Shape(name="square", sides=4)
    assert usage.response_id == "gen-1" and usage.prompt_tokens == 12 and usage.completion_tokens == 7
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "openai/gpt-5-mini"
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["messages"][1] == {"role": "user", "content": "user text"}
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "shape"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert body["provider"] == {"require_parameters": True}
    assert route.calls.last.request.headers["authorization"] == "Bearer key"


@respx.mock
def test_parse_retries_once_on_server_error_then_raises_unavailable() -> None:
    route = respx.post(URL).mock(side_effect=[httpx.Response(503), httpx.Response(503)])
    client = StructuredOutputClient("key", "m", httpx.Client())
    with pytest.raises(AIUnavailable):
        client.parse("s", "u", Shape, "shape")
    assert route.call_count == 2


@respx.mock
def test_parse_raises_invalid_output_when_json_does_not_match_schema() -> None:
    respx.post(URL).mock(return_value=ok(json.dumps({"name": "circle"})))
    client = StructuredOutputClient("key", "m", httpx.Client())
    with pytest.raises(AIInvalidOutput):
        client.parse("s", "u", Shape, "shape")


@respx.mock
def test_error_messages_never_include_the_key() -> None:
    respx.post(URL).mock(return_value=httpx.Response(401, json={"error": "bad key"}))
    client = StructuredOutputClient("sk-secret-value", "m", httpx.Client())
    with pytest.raises(AIUnavailable) as info:
        client.parse("s", "u", Shape, "shape")
    assert "sk-secret-value" not in str(info.value)
```

Add to `tests/test_config.py`:

```python
def test_trade_settings_defaults() -> None:
    settings = Settings(**BASE)
    assert settings.trade_extraction_model == "openai/gpt-5-mini"
    assert settings.sleeper_players_ttl_hours == 24
    assert settings.openrouter_api_key is None
```

- [ ] **Step 2: Run the tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/ai packages/league-automation/tests/test_config.py -v`

Expected: FAIL, `ultimate_guillotine.ai` missing and the new settings absent.

- [ ] **Step 3: Implement the settings and the client**

Add the three fields to `Settings` (after `discord_alerts_channel`) and the three upper-case names with empty values to `.env.example`.

```python
# packages/league-automation/src/ultimate_guillotine/ai/openrouter.py
"""One structured-output call to OpenRouter. The only language-model boundary in the package."""
import json
from dataclasses import dataclass
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class AIUnavailable(Exception):
    """Transport failure, non-2xx status, or provider refusal. Safe to retry later."""


class AIInvalidOutput(Exception):
    """The model answered but not with JSON matching the schema."""


@dataclass(frozen=True)
class AIUsage:
    response_id: str
    prompt_tokens: int
    completion_tokens: int
    model: str


class StructuredOutputClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        http: httpx.Client,
        base_url: str = "https://openrouter.ai/api/v1",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._http = http
        self._base = base_url.rstrip("/")

    def parse(self, system: str, user: str, schema: type[T], schema_name: str) -> tuple[T, AIUsage]:
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": _strict_schema(schema),
                },
            },
            "provider": {"require_parameters": True},
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        last_error = "no attempt"
        for _attempt in range(2):
            try:
                response = self._http.post(
                    f"{self._base}/chat/completions", json=body, headers=headers, timeout=60.0
                )
            except httpx.HTTPError as exc:
                last_error = exc.__class__.__name__
                continue
            if response.status_code >= 500:
                last_error = f"status {response.status_code}"
                continue
            if response.status_code != 200:
                raise AIUnavailable(f"openrouter returned status {response.status_code}")
            return _parse_response(response.json(), schema)
        raise AIUnavailable(f"openrouter unavailable after retry: {last_error}")


def _strict_schema(schema: type[BaseModel]) -> dict:
    """Pydantic JSON schema with additionalProperties=false on every object, as strict mode requires."""
    raw = schema.model_json_schema()

    def harden(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}).keys())
            for value in node.values():
                harden(value)
        elif isinstance(node, list):
            for item in node:
                harden(item)

    harden(raw)
    return raw


def _parse_response(payload: dict, schema: type[T]) -> tuple[T, AIUsage]:
    try:
        content = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage") or {}
        meta = AIUsage(
            response_id=str(payload.get("id", "")),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            model=str(payload.get("model", "")),
        )
    except (KeyError, IndexError, TypeError) as exc:
        raise AIInvalidOutput(f"unexpected response shape: {exc.__class__.__name__}") from exc
    try:
        return schema.model_validate(json.loads(content)), meta
    except (json.JSONDecodeError, ValidationError) as exc:
        raise AIInvalidOutput(f"model output did not match schema: {exc.__class__.__name__}") from exc
```

Strict mode requires every property to be listed in `required`; optional fields are therefore declared in Pydantic models as `X | None` with a default of `None` so the model must emit `null` explicitly. Task 3's `ExtractedTrade` follows that rule.

- [ ] **Step 4: Run green, lint, commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation .env.example
git commit -m "feat: add OpenRouter structured-output client and trade settings"
```

### Task 2: Player directory (table, Sleeper fetch, daily sync)

**Files:**
- Create through CLI: `supabase/migrations/<generated>_players_and_trade_fingerprints.sql`
- Create: `supabase/tests/trades.sql`
- Modify: `packages/league-automation/src/ultimate_guillotine/sleeper/client.py`
- Create: `packages/league-automation/src/ultimate_guillotine/sleeper/players.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/sleeper.py`
- Create: `packages/league-automation/tests/fixtures/sleeper/players_small.json`
- Create: `packages/league-automation/tests/sleeper/test_players.py`
- Modify: `hermes/guillotine/cron.yaml`
- Create: `hermes/guillotine/scripts/guillotine_players_sync.sh.template`

**Interfaces:**
- Consumes: `SleeperClient`, `conn` fixture, cron manifest format from the foundation.
- Produces:
  - Table `public.players(id identity, created_at, sleeper_player_id text unique, full_name text, first_name text, last_name text, position text, team text, active boolean, synced_at timestamptz)` with RLS, public select policies, and the `Automation writes players` policy; plus the trade columns below.
  - Columns `public.trade_revisions.semantic_fingerprint text` (nullable for pre-existing rows, unique partial index where not null) and `public.trades.context_key text` (indexed).
  - `SleeperClient.get_players() -> dict[str, dict[str, Any]]`.
  - `@dataclass(frozen=True) class Player: sleeper_player_id: str; full_name: str; position: str | None; team: str | None; active: bool`.
  - `sync_players(client, conn, now: datetime) -> int` (upserts skill positions `QB, RB, WR, TE, K, DEF` and active players only; returns rows written).
  - `PlayerRepository(conn).all_active() -> list[Player]` and `.last_synced_at() -> datetime | None`.
  - `ug sleeper players [--quiet]` recording agent `players-sync`.

- [ ] **Step 1: Write the failing tests**

Fixture `players_small.json` holds eight entries in Sleeper's shape (keys are ids): three WRs including two named `Mike Williams` on different teams, one `DEF` entry keyed `KC` with `first_name: "Kansas City"`, `last_name: "Chiefs"`, one inactive player, one `OL` player, and one with `full_name` missing but first and last present.

```python
# packages/league-automation/tests/sleeper/test_players.py
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx

from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.players import PlayerRepository, load_players, sync_players

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sleeper" / "players_small.json"


def test_load_players_keeps_only_active_skill_positions_and_defenses() -> None:
    players = load_players(json.loads(FIXTURE.read_text()))
    names = {p.full_name for p in players}
    assert "Kansas City Chiefs" in names
    assert all(p.active for p in players)
    assert not any(p.position == "OL" for p in players)
    assert sum(1 for p in players if p.full_name == "Mike Williams") == 2


@respx.mock
def test_get_players_hits_sleeper() -> None:
    respx.get("https://api.sleeper.app/v1/players/nfl").mock(
        return_value=httpx.Response(200, json=json.loads(FIXTURE.read_text()))
    )
    assert "KC" in SleeperClient(httpx.Client()).get_players()


def test_sync_players_upserts_and_records_time(conn) -> None:
    class FakeClient:
        def get_players(self):
            return json.loads(FIXTURE.read_text())

    now = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    written = sync_players(FakeClient(), conn, now)
    assert written >= 5
    assert sync_players(FakeClient(), conn, now) == written
    repo = PlayerRepository(conn)
    assert repo.last_synced_at() == now
    assert any(p.full_name == "Kansas City Chiefs" for p in repo.all_active())
```

- [ ] **Step 2: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper/test_players.py -v`

Expected: FAIL, `sleeper.players` missing.

- [ ] **Step 3: Create the migration**

Run: `supabase migration new players_and_trade_fingerprints`

```sql
create table public.players (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  sleeper_player_id text not null unique,
  full_name text not null,
  first_name text,
  last_name text,
  position text,
  team text,
  active boolean not null default true,
  synced_at timestamptz not null
);
create index players_full_name_idx on public.players (lower(full_name));

alter table public.players enable row level security;
revoke all on public.players from anon, authenticated;
grant select on public.players to anon, authenticated;
create policy "Public players are readable" on public.players for select using (true);
create policy "Automation writes players" on public.players
  for all to automation_worker using (true) with check (true);
grant select, insert, update on public.players to automation_worker;
grant usage, select on all sequences in schema public to automation_worker;

alter table public.trade_revisions add column semantic_fingerprint text;
create unique index trade_revisions_semantic_fingerprint_key
  on public.trade_revisions (semantic_fingerprint) where semantic_fingerprint is not null;
alter table public.trades add column context_key text;
create index trades_context_key_idx on public.trades (context_key);
```

Add `supabase/tests/trades.sql` with `plan(6)`: `has_table('public','players','players table exists')`, `has_column('public','trade_revisions','semantic_fingerprint','fingerprint column exists')`, `has_column('public','trades','context_key','context key exists')`, `policies_are('public','players', array['Public players are readable','Automation writes players'])`, an `is_empty` over `role_table_grants` for `automation_worker` with `privilege_type = 'DELETE'` and `table_name = 'players'`, and a `throws_ok` that inserting two `trade_revisions` rows with the same non-null `semantic_fingerprint` violates the unique index (create a season/trade row first inside the transaction). Follow the description-argument style of the existing pgTAP files.

Run: `supabase db reset && supabase test db`

- [ ] **Step 4: Implement the fetch, loader, repository, sync, and CLI**

`SleeperClient.get_players` is `GET /players/nfl` with `timeout=60.0`, `raise_for_status()`, returning the JSON dict.

```python
# packages/league-automation/src/ultimate_guillotine/sleeper/players.py
from dataclasses import dataclass
from datetime import datetime
from typing import Any

SKILL_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}


@dataclass(frozen=True)
class Player:
    sleeper_player_id: str
    full_name: str
    position: str | None
    team: str | None
    active: bool


def load_players(raw: dict[str, dict[str, Any]]) -> list[Player]:
    players: list[Player] = []
    for pid, rec in raw.items():
        position = rec.get("position")
        if position not in SKILL_POSITIONS or not rec.get("active", False):
            continue
        name = rec.get("full_name") or " ".join(
            p for p in (rec.get("first_name"), rec.get("last_name")) if p
        )
        if not name:
            continue
        players.append(Player(str(pid), name, position, rec.get("team"), True))
    return players


class PlayerRepository:
    def __init__(self, conn) -> None:
        self._conn = conn

    def upsert_many(self, players: list[Player], now: datetime) -> int:
        with self._conn.cursor() as cur:
            cur.executemany(
                """
                insert into public.players
                  (sleeper_player_id, full_name, position, team, active, synced_at)
                values (%s, %s, %s, %s, %s, %s)
                on conflict (sleeper_player_id) do update set
                  full_name = excluded.full_name, position = excluded.position,
                  team = excluded.team, active = excluded.active, synced_at = excluded.synced_at
                """,
                [(p.sleeper_player_id, p.full_name, p.position, p.team, p.active, now)
                 for p in players],
            )
        return len(players)

    def all_active(self) -> list[Player]:
        with self._conn.cursor() as cur:
            cur.execute(
                "select sleeper_player_id, full_name, position, team, active "
                "from public.players where active order by full_name"
            )
            return [Player(*row) for row in cur.fetchall()]

    def last_synced_at(self) -> datetime | None:
        with self._conn.cursor() as cur:
            cur.execute("select max(synced_at) from public.players")
            row = cur.fetchone()
            return row[0] if row else None


def sync_players(client, conn, now: datetime) -> int:
    players = load_players(client.get_players())
    with conn.transaction():
        return PlayerRepository(conn).upsert_many(players, now)
```

`ug sleeper players [--quiet]` in `cli/sleeper.py` mirrors `ug sleeper sync`: it runs `sync_players(SleeperClient(httpx.Client()), conn, now)` through `run_scheduled(conn, "players-sync", now, action)` and prints `players sync: N players` unless `--quiet`.

Append to `hermes/guillotine/cron.yaml`:

```yaml
  - name: guillotine-players-sync
    agent: players-sync
    schedule: "30 5 * * *"
    script: guillotine_players_sync.sh
    deliver: "discord:#guillotine-ops"
    max_gap_minutes: 1500
```

and the template `guillotine_players_sync.sh.template` identical to the sleeper sync template but ending in `ug sleeper players --quiet`.

- [ ] **Step 5: Run green, reinstall the profile, commit**

Run: `pnpm test:agents` (with `TEST_DATABASE_URL`) `&& pnpm lint:agents && bash hermes/guillotine/install.sh && uv run --project packages/league-automation ug sleeper players`

Expected: tests PASS; install registers the fifth job; the live sync prints a count in the thousands.

```bash
git add supabase packages/league-automation hermes
git commit -m "feat: add player directory and trade fingerprint columns"
```

### Task 3: Trade models, detection, and fingerprints

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/trades/__init__.py`
- Create: `packages/league-automation/src/ultimate_guillotine/trades/models.py`
- Create: `packages/league-automation/src/ultimate_guillotine/trades/detect.py`
- Create: `packages/league-automation/src/ultimate_guillotine/trades/fingerprint.py`
- Create: `packages/league-automation/tests/trades/__init__.py`
- Create: `packages/league-automation/tests/trades/test_detect.py`
- Create: `packages/league-automation/tests/trades/test_fingerprint.py`
- Create: `packages/league-automation/tests/fixtures/trades/alerts.json`

**Interfaces:**
- Produces:
  - `is_trade_candidate(text: str) -> bool`, `is_rescission_candidate(text: str) -> bool`.
  - Pydantic models (all `frozen=True`, `extra="forbid"`):
    - `ExtractedParty(name: str)`
    - `ExtractedAsset(kind: Literal["player","faab","draft_dollars","usd","protection","other"], from_party: str | None, to_party: str | None, player_name: str | None, amount: int | None, unit: Literal["faab","draft_dollars","usd"] | None, description: str | None)`
    - `ExtractedTrade(kind: Literal["permanent","rental","payment","rescission","unclear"], parties: list[ExtractedParty], assets: list[ExtractedAsset], effective_week: int | None, rental_return_condition: str | None, special_terms: list[str], referenced_trade_code: str | None, unclear_reason: str | None)`
    - `TradeParty(member_id: int, display_name: str)`
    - `TradeAsset(kind, from_member_id: int | None, to_member_id: int | None, player_id: str | None, player_name: str | None, amount: int | None, unit: str | None, description: str | None)`
    - `TradeProposal(season: int, effective_week: int | None, kind, parties: list[TradeParty], assets: list[TradeAsset], rental_return_condition: str | None, special_terms: list[str], referenced_trade_code: str | None, source_message_guid: str, evidence_excerpt: str, prompt_version: str, model: str)`
  - `message_fingerprint(text) -> str`, `trade_fingerprint(proposal) -> str` (64 hex), `trade_context_key(proposal) -> str`.

- [ ] **Step 1: Write the fixture and failing tests**

`alerts.json` is a list of objects `{"id", "category", "text", "expect_candidate", "expect_rescission"}` covering: `permanent`, `faab_only`, `rental`, `multi_party`, `option`, `payment_no_trade`, `duplicate_repost` (same text as `permanent` with extra whitespace), `amended` (permanent with a different FAAB amount), `rescission`, `ambiguous` (`"🚨 Chase rented for 10"`), and two negatives (`"🚨 huge game tonight"`, `"Member01 sends Player A to Member02"`). Member names are `Member01`..`Member04`; player names are `Player Alpha`, `Player Beta`, `Player Gamma`, `Kansas City Chiefs`.

```python
# packages/league-automation/tests/trades/test_detect.py
import json
from pathlib import Path

import pytest

from ultimate_guillotine.trades.detect import is_rescission_candidate, is_trade_candidate

ALERTS = json.loads((Path(__file__).parent.parent / "fixtures" / "trades" / "alerts.json").read_text())


@pytest.mark.parametrize("alert", ALERTS, ids=[a["id"] for a in ALERTS])
def test_candidate_detection_matches_fixture(alert: dict) -> None:
    assert is_trade_candidate(alert["text"]) is alert["expect_candidate"]
    assert is_rescission_candidate(alert["text"]) is alert["expect_rescission"]


def test_detection_is_case_and_inflection_insensitive() -> None:
    assert is_trade_candidate("🚨 MEMBER01 TRADED Player Alpha to member02")
    assert is_trade_candidate("🚨 member03 is renting Player Beta from member04 for 20 faab")
    assert not is_trade_candidate("🚨 who is sending the trophy pics")  # 'sending' alone, no asset words? see Step 3
```

The third assertion documents the rule that `send` counts only with an object clause; if Step 3's word list makes it true, change the expectation to `True` and note it in the report. Keep the rule simple: emoji plus any term from the list.

```python
# packages/league-automation/tests/trades/test_fingerprint.py
from ultimate_guillotine.trades.fingerprint import message_fingerprint, trade_context_key, trade_fingerprint
from ultimate_guillotine.trades.models import TradeAsset, TradeParty, TradeProposal


def proposal(**overrides) -> TradeProposal:
    base = dict(
        season=2026, effective_week=2, kind="permanent",
        parties=[TradeParty(1, "Member01"), TradeParty(2, "Member02")],
        assets=[
            TradeAsset("player", 1, 2, "p1", "Player Alpha", None, None, None),
            TradeAsset("faab", 2, 1, None, None, 450, "faab", None),
        ],
        rental_return_condition=None, special_terms=[], referenced_trade_code=None,
        source_message_guid="g1", evidence_excerpt="🚨 ...", prompt_version="2026.1", model="m",
    )
    base.update(overrides)
    return TradeProposal(**base)


def test_message_fingerprint_ignores_case_and_whitespace() -> None:
    assert message_fingerprint("🚨 A  sends B") == message_fingerprint("🚨 a sends b\n")


def test_trade_fingerprint_ignores_order_and_source() -> None:
    reordered = proposal(
        parties=[TradeParty(2, "Member02"), TradeParty(1, "Member01")],
        assets=list(reversed(proposal().assets)), source_message_guid="g2", evidence_excerpt="x",
    )
    assert trade_fingerprint(proposal()) == trade_fingerprint(reordered)
    assert len(trade_fingerprint(proposal())) == 64


def test_trade_fingerprint_changes_with_amount_or_week_or_return_condition() -> None:
    amended = proposal(assets=[proposal().assets[0], TradeAsset("faab", 2, 1, None, None, 500, "faab", None)])
    assert trade_fingerprint(amended) != trade_fingerprint(proposal())
    assert trade_fingerprint(proposal(effective_week=3)) != trade_fingerprint(proposal())
    assert trade_fingerprint(proposal(rental_return_condition="returned Monday")) != trade_fingerprint(proposal())


def test_context_key_is_stable_across_amounts() -> None:
    amended = proposal(assets=[proposal().assets[0], TradeAsset("faab", 2, 1, None, None, 500, "faab", None)])
    assert trade_context_key(amended) == trade_context_key(proposal())
    assert trade_context_key(proposal(parties=[TradeParty(1, "Member01"), TradeParty(3, "Member03")])) != trade_context_key(proposal())
```

- [ ] **Step 2: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/trades -v`

- [ ] **Step 3: Implement**

```python
# packages/league-automation/src/ultimate_guillotine/trades/detect.py
import re

ALERT = "🚨"
TRADE_TERMS = re.compile(
    r"\b(send|sends|sent|sending|receive|receives|received|trade|trades|traded|trading|"
    r"buy|buys|bought|sell|sells|sold|rent|rents|rented|renting|swap|swaps|swapped|"
    r"faab|option|protection|pays|paid|insurance|for)\b",
    re.IGNORECASE,
)
RESCIND_TERMS = re.compile(r"\b(rescind|rescinds|rescinded|cancel|cancels|cancelled|canceled|void|voided)\b", re.IGNORECASE)


def is_trade_candidate(text: str) -> bool:
    return ALERT in text and TRADE_TERMS.search(text) is not None


def is_rescission_candidate(text: str) -> bool:
    return ALERT in text and RESCIND_TERMS.search(text) is not None
```

Remove `for` from `TRADE_TERMS` if the negative fixture `"🚨 huge game tonight"` stays negative without it and the positives still pass; the list must make every fixture expectation hold.

```python
# packages/league-automation/src/ultimate_guillotine/trades/fingerprint.py
import hashlib
import json

from ultimate_guillotine.trades.models import TradeProposal


def message_fingerprint(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).lower().encode()).hexdigest()


def _canonical_asset(asset) -> list:
    return [
        asset.kind, asset.from_member_id, asset.to_member_id, asset.player_id,
        (asset.player_name or "").lower(), asset.amount, asset.unit,
        " ".join((asset.description or "").split()).lower(),
    ]


def trade_fingerprint(proposal: TradeProposal) -> str:
    canonical = {
        "season": proposal.season,
        "week": proposal.effective_week,
        "kind": proposal.kind,
        "parties": sorted(p.member_id for p in proposal.parties),
        "assets": sorted(_canonical_asset(a) for a in proposal.assets),
        "return": " ".join((proposal.rental_return_condition or "").split()).lower(),
        "special": sorted(" ".join(t.split()).lower() for t in proposal.special_terms),
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, default=str).encode()).hexdigest()


def trade_context_key(proposal: TradeProposal) -> str:
    players = sorted(a.player_id or (a.player_name or "").lower() for a in proposal.assets if a.kind == "player")
    parties = sorted(p.member_id for p in proposal.parties)
    return f"{proposal.season}:{','.join(map(str, parties))}:{','.join(players)}"
```

`models.py` defines the Pydantic classes exactly as listed in Interfaces, with `model_config = ConfigDict(frozen=True, extra="forbid")`. `TradeAsset` and `TradeParty` are plain frozen dataclasses (positional construction is used in tests).

- [ ] **Step 4: Run green, lint, commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation/src/ultimate_guillotine/trades packages/league-automation/tests/trades packages/league-automation/tests/fixtures/trades
git commit -m "feat: add trade models, alert detection, and fingerprints"
```

### Task 4: Name resolution and validation

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/trades/resolve.py`
- Create: `packages/league-automation/tests/trades/test_resolve.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/data/repositories.py` (add `MemberAliasRepository`)

**Interfaces:**
- Consumes: `ExtractedTrade`, `Player`, `TradeParty`, `TradeAsset`, `TradeProposal`.
- Produces:
  - `@dataclass(frozen=True) class MemberRef: member_id: int; display_name: str; aliases: tuple[str, ...]`.
  - `MemberAliasRepository(conn).all_members() -> list[MemberRef]` reading `public.members` joined with `private.member_contacts.alias` (aliases may be empty).
  - `class Unresolved(Exception)` carrying `.reason: str` (a short human sentence such as `Two players named Mike Williams; which team?`).
  - `resolve_extracted(extracted: ExtractedTrade, members: list[MemberRef], players: list[Player], season: int, source_guid: str, excerpt: str, prompt_version: str, model: str) -> TradeProposal` raising `Unresolved` on any ambiguity or missing requirement.
  - `validate(proposal: TradeProposal) -> None` raising `Unresolved` when fewer than two parties, no asset, an amount without a unit, or `kind == "rental"` with no return condition.

- [ ] **Step 1: Write the failing tests**

```python
# packages/league-automation/tests/trades/test_resolve.py
import pytest

from ultimate_guillotine.sleeper.players import Player
from ultimate_guillotine.trades.models import ExtractedAsset, ExtractedParty, ExtractedTrade
from ultimate_guillotine.trades.resolve import MemberRef, Unresolved, resolve_extracted, validate

MEMBERS = [MemberRef(1, "Member01", ("m1", "memberone")), MemberRef(2, "Member02", ()), MemberRef(3, "Member03", ())]
PLAYERS = [
    Player("p1", "Player Alpha", "WR", "KC", True),
    Player("p2", "Mike Williams", "WR", "NYJ", True),
    Player("p3", "Mike Williams", "WR", "PIT", True),
    Player("KC", "Kansas City Chiefs", "DEF", "KC", True),
]


def extracted(**overrides) -> ExtractedTrade:
    base = dict(
        kind="permanent", parties=[ExtractedParty(name="member01"), ExtractedParty(name="Member02")],
        assets=[
            ExtractedAsset(kind="player", from_party="member01", to_party="Member02", player_name="player alpha", amount=None, unit=None, description=None),
            ExtractedAsset(kind="faab", from_party="Member02", to_party="member01", player_name=None, amount=450, unit="faab", description=None),
        ],
        effective_week=2, rental_return_condition=None, special_terms=[], referenced_trade_code=None, unclear_reason=None,
    )
    base.update(overrides)
    return ExtractedTrade(**base)


def resolve(e: ExtractedTrade):
    return resolve_extracted(e, MEMBERS, PLAYERS, 2026, "g1", "🚨 ...", "2026.1", "m")


def test_resolves_members_by_name_or_alias_and_players_by_name() -> None:
    proposal = resolve(extracted(parties=[ExtractedParty(name="memberone"), ExtractedParty(name="Member02")]))
    assert [p.member_id for p in proposal.parties] == [1, 2]
    assert proposal.assets[0].player_id == "p1"
    assert proposal.assets[1].amount == 450 and proposal.assets[1].unit == "faab"


def test_ambiguous_player_name_is_unresolved_with_reason() -> None:
    e = extracted(assets=[ExtractedAsset(kind="player", from_party="member01", to_party="Member02", player_name="Mike Williams", amount=None, unit=None, description=None)])
    with pytest.raises(Unresolved) as info:
        resolve(e)
    assert "Mike Williams" in info.value.reason


def test_unknown_member_is_unresolved() -> None:
    with pytest.raises(Unresolved):
        resolve(extracted(parties=[ExtractedParty(name="Nobody"), ExtractedParty(name="Member02")]))


def test_model_flagged_unclear_is_unresolved_with_its_reason() -> None:
    with pytest.raises(Unresolved) as info:
        resolve(extracted(kind="unclear", unclear_reason="No counterparty named"))
    assert info.value.reason == "No counterparty named"


def test_validate_requires_two_parties_one_asset_units_and_return_condition() -> None:
    good = resolve(extracted())
    validate(good)
    with pytest.raises(Unresolved):
        validate(resolve(extracted(parties=[ExtractedParty(name="Member01"), ExtractedParty(name="Member01")])))
    with pytest.raises(Unresolved):
        validate(resolve(extracted(assets=[])))
    with pytest.raises(Unresolved):
        validate(resolve(extracted(kind="rental")))
```

- [ ] **Step 2: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/trades/test_resolve.py -v`

- [ ] **Step 3: Implement**

Normalization: NFKC, lower-case, strip punctuation except spaces, collapse whitespace. Member lookup: exact normalized match on display name or any alias; zero matches or more than one raises `Unresolved(f"I don't recognize '{name}' as a league member")`. Player lookup: exact normalized `full_name` match first; if none, last-name-only match when unique; two or more matches raise `Unresolved(f"Two players named {name}; which team?")`; zero raise `Unresolved(f"I can't find a player named {name}")`. Defenses match on full name (`Kansas City Chiefs`) or on `team` code plus the word `defense`/`DEF`/`D/ST`. `kind == "unclear"` raises `Unresolved(unclear_reason or "The alert is unclear")`. Duplicate parties collapse to one and then fail validation. `validate` enforces the rules in Interfaces; error sentences are user-facing and end without a period so the formatter can compose them.

`MemberAliasRepository.all_members` runs:

```sql
select m.id, m.display_name, coalesce(array_agg(c.alias) filter (where c.alias is not null), '{}')
from public.members m left join private.member_contacts c on c.member_id = m.id
group by m.id, m.display_name order by m.id
```

- [ ] **Step 4: Run green, lint, commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation/src/ultimate_guillotine/trades/resolve.py packages/league-automation/src/ultimate_guillotine/data/repositories.py packages/league-automation/tests/trades/test_resolve.py
git commit -m "feat: resolve trade names deterministically and validate proposals"
```

### Task 5: Versioned prompt and extraction

**Files:**
- Create: `agents/trade-registrar/prompt.md`
- Create: `packages/league-automation/src/ultimate_guillotine/trades/extract.py`
- Create: `packages/league-automation/tests/trades/test_extract.py`

**Interfaces:**
- Consumes: `StructuredOutputClient.parse`, `ExtractedTrade`.
- Produces: `PROMPT_VERSION = "2026.1"`, `load_prompt() -> str` (reads `agents/trade-registrar/prompt.md` relative to the repository root, resolved from this file's location), `extract_trade(client: StructuredOutputClient, text: str, season: int, week_hint: int | None, member_names: list[str]) -> tuple[ExtractedTrade, AIUsage]`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/league-automation/tests/trades/test_extract.py
from ultimate_guillotine.ai.openrouter import AIUsage
from ultimate_guillotine.trades.extract import PROMPT_VERSION, extract_trade, load_prompt
from ultimate_guillotine.trades.models import ExtractedAsset, ExtractedParty, ExtractedTrade


class FakeAI:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def parse(self, system, user, schema, schema_name):
        self.calls.append((system, user, schema, schema_name))
        return self.result, AIUsage("gen-1", 10, 5, "m")


def test_prompt_is_versioned_and_states_the_rules() -> None:
    prompt = load_prompt()
    assert PROMPT_VERSION == "2026.1"
    assert "verbatim" in prompt and "null" in prompt and "fairness" in prompt


def test_extract_passes_context_and_returns_model_output() -> None:
    expected = ExtractedTrade(
        kind="rental", parties=[ExtractedParty(name="Member03"), ExtractedParty(name="Member04")],
        assets=[ExtractedAsset(kind="player", from_party="Member04", to_party="Member03", player_name="Player Beta", amount=None, unit=None, description=None),
                ExtractedAsset(kind="faab", from_party="Member03", to_party="Member04", player_name=None, amount=92, unit="faab", description=None)],
        effective_week=2, rental_return_condition="50 FAAB returned Monday", special_terms=[], referenced_trade_code=None, unclear_reason=None,
    )
    ai = FakeAI(expected)
    result, usage = extract_trade(ai, "🚨 Member03 rents Player Beta from Member04 for 92 FAAB, 50 returned Monday", 2026, 2, ["Member03", "Member04"])
    assert result == expected and usage.response_id == "gen-1"
    system, user, schema, name = ai.calls[0]
    assert schema is ExtractedTrade and name == "extracted_trade"
    assert "Member03" in user and "Season: 2026" in user and "Week hint: 2" in user
    assert system == load_prompt()
```

- [ ] **Step 2: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/trades/test_extract.py -v`

- [ ] **Step 3: Write the prompt and the extractor**

`agents/trade-registrar/prompt.md` (version header first line `<!-- prompt_version: 2026.1 -->`) says, in this order: you convert one fantasy football trade announcement into structured fields; extract only what the text states explicitly; use `null` for anything not stated; copy unusual conditions verbatim into `special_terms`; never judge fairness and never invent a counterparty, amount, or player; classify `kind` as `permanent`, `rental` (a player returns later), `payment` (money or FAAB with no player), `rescission` (the text cancels a prior trade), or `unclear`; set `unclear` with a one-sentence `unclear_reason` when fewer than two people or no asset is named; amounts are integers with units `faab`, `draft_dollars`, or `usd`; `effective_week` is a number only if stated; party names are copied as written.

```python
# packages/league-automation/src/ultimate_guillotine/trades/extract.py
from pathlib import Path

from ultimate_guillotine.ai.openrouter import AIUsage, StructuredOutputClient
from ultimate_guillotine.trades.models import ExtractedTrade

PROMPT_VERSION = "2026.1"
_PROMPT_PATH = Path(__file__).resolve().parents[4] / "agents" / "trade-registrar" / "prompt.md"


def load_prompt() -> str:
    return _PROMPT_PATH.read_text()


def extract_trade(
    client: StructuredOutputClient,
    text: str,
    season: int,
    week_hint: int | None,
    member_names: list[str],
) -> tuple[ExtractedTrade, AIUsage]:
    user = (
        f"Season: {season}\nWeek hint: {week_hint if week_hint is not None else 'unknown'}\n"
        f"League members: {', '.join(member_names)}\n\nAnnouncement:\n{text}"
    )
    return client.parse(load_prompt(), user, ExtractedTrade, "extracted_trade")
```

Confirm `parents[4]` resolves to the repository root from `packages/league-automation/src/ultimate_guillotine/trades/extract.py` (trades → ultimate_guillotine → src → league-automation → packages → root is five levels; adjust the index so the test passes and say which in the report).

- [ ] **Step 4: Run green, lint, commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add agents/trade-registrar/prompt.md packages/league-automation/src/ultimate_guillotine/trades/extract.py packages/league-automation/tests/trades/test_extract.py
git commit -m "feat: add versioned trade extraction prompt"
```

### Task 6: Trade repository with idempotent accept, revise, and rescind

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/trades/repository.py`
- Create: `packages/league-automation/tests/trades/test_repository.py`

**Interfaces:**
- Consumes: `TradeProposal`, `trade_fingerprint`, `trade_context_key`, `conn` fixture.
- Produces:
  - `@dataclass(frozen=True) class TradeAcceptance: status: Literal["created","duplicate","revised"]; trade_id: int; trade_code: str; revision: int; previous_terms: dict | None`.
  - `TradeRepository(conn).accept(proposal: TradeProposal) -> TradeAcceptance`, `.rescind(trade_code: str, source_guid: str, occurred_at) -> bool`, `.find_by_code(code) -> dict | None` (trade row plus current terms), `.find_by_context(context_key) -> int | None`, `.list_recent(limit=10) -> list[dict]`.
  - Trade codes are `T-<season>-<three-digit sequence>` allocated as `count(trades in season) + 1` inside the transaction.

- [ ] **Step 1: Write the failing DB tests**

```python
# packages/league-automation/tests/trades/test_repository.py
from datetime import UTC, datetime

from ultimate_guillotine.trades.models import TradeAsset, TradeParty, TradeProposal
from ultimate_guillotine.trades.repository import TradeRepository


def make(conn, **overrides) -> TradeProposal:
    with conn.cursor() as cur:
        cur.execute("insert into public.members (display_name) values ('Member01'), ('Member02') on conflict do nothing")
        cur.execute("select id from public.members where display_name in ('Member01','Member02') order by display_name")
        m1, m2 = [r[0] for r in cur.fetchall()]
    base = dict(
        season=2026, effective_week=2, kind="permanent",
        parties=[TradeParty(m1, "Member01"), TradeParty(m2, "Member02")],
        assets=[TradeAsset("player", m1, m2, "p1", "Player Alpha", None, None, None),
                TradeAsset("faab", m2, m1, None, None, 450, "faab", None)],
        rental_return_condition=None, special_terms=[], referenced_trade_code=None,
        source_message_guid="g1", evidence_excerpt="🚨 ...", prompt_version="2026.1", model="m",
    )
    base.update(overrides)
    return TradeProposal(**base)


def test_accept_creates_then_detects_duplicate_and_revision(conn) -> None:
    repo = TradeRepository(conn)
    first = repo.accept(make(conn))
    assert first.status == "created" and first.trade_code == "T-2026-001" and first.revision == 1
    dup = repo.accept(make(conn, source_message_guid="g2", evidence_excerpt="repost"))
    assert dup.status == "duplicate" and dup.trade_id == first.trade_id
    amended = make(conn, source_message_guid="g3", assets=[make(conn).assets[0], TradeAsset("faab", make(conn).parties[1].member_id, make(conn).parties[0].member_id, None, None, 500, "faab", None)])
    revised = repo.accept(amended)
    assert revised.status == "revised" and revised.revision == 2 and revised.trade_id == first.trade_id
    assert revised.previous_terms["assets"][1]["amount"] == 450
    current = repo.find_by_code("T-2026-001")
    assert current["terms"]["assets"][1]["amount"] == 500 and current["status"] == "accepted"


def test_rescind_marks_trade_and_writes_event(conn) -> None:
    repo = TradeRepository(conn)
    created = repo.accept(make(conn))
    assert repo.rescind(created.trade_code, "g9", datetime.now(UTC)) is True
    assert repo.find_by_code(created.trade_code)["status"] == "rescinded"
    with conn.cursor() as cur:
        cur.execute("select count(*) from public.league_events where event_type = 'trade_rescinded'")
        assert cur.fetchone()[0] == 1
    assert repo.rescind("T-2026-999", "g9", datetime.now(UTC)) is False
```

- [ ] **Step 2: Run red**

Run: `TEST_DATABASE_URL=... uv run --project packages/league-automation pytest packages/league-automation/tests/trades/test_repository.py -v`

- [ ] **Step 3: Implement**

`accept` runs inside `with conn.transaction():`:

1. `fingerprint = trade_fingerprint(proposal)`, `context = trade_context_key(proposal)`, `terms = proposal.model_dump(mode="json")`.
2. `select r.trade_id, t.trade_code, r.revision from public.trade_revisions r join public.trades t on t.id = r.trade_id where r.semantic_fingerprint = %s` → if a row exists return `duplicate`.
3. `select id, trade_code, current_revision_id from public.trades where context_key = %s and status = 'accepted' and season_id = (select id from public.seasons where year = %s)` → if found: read the current revision's `terms` as `previous_terms`, insert the next revision (`revision = max(revision)+1`) with `semantic_fingerprint`, `source_message_guid`, `effective_week`, update `trades.current_revision_id`, return `revised`.
4. Otherwise allocate the code: `select count(*) from public.trades where season_id = %s` plus one, formatted `T-{season}-{n:03d}`; insert `trades (season_id, trade_code, context_key)`; insert revision 1; update `current_revision_id`; insert `public.league_events (season_id, week, event_type, occurred_at, payload, idempotency_key)` with `event_type = 'trade'`, payload `{"trade_code", "revision": 1}`, `idempotency_key = f"trade:{fingerprint}"`; return `created`.

A `UniqueViolation` on the fingerprint index (a concurrent duplicate) is caught and converted to `duplicate` by re-running step 2 in a fresh transaction.

`rescind` updates `trades.status = 'rescinded'` for the code (returning `False` when no row), inserts a `league_events` row with `event_type = 'trade_rescinded'`, payload `{"trade_code", "source_message_guid"}`, `idempotency_key = f"rescind:{trade_code}:{source_guid}"` with `on conflict do nothing`, and returns `True`.

`find_by_code` joins `trades` to its current revision and returns `{"trade_id", "trade_code", "status", "revision", "terms", "effective_week"}`. `list_recent` returns the same shape for the newest `limit` trades.

- [ ] **Step 4: Run green (with the database), lint, commit**

Run: `TEST_DATABASE_URL=... pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation/src/ultimate_guillotine/trades/repository.py packages/league-automation/tests/trades/test_repository.py
git commit -m "feat: persist deduplicated trade revisions and rescissions"
```

### Task 7: Message formatting

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/trades/format.py`
- Create: `packages/league-automation/tests/trades/test_format.py`

**Interfaces:**
- Produces: `format_confirmation(code: str, proposal: TradeProposal) -> str`, `format_updated(code: str, proposal: TradeProposal, previous_terms: dict) -> str`, `format_rescinded(code: str) -> str`, `format_clarification(reason: str) -> str`. None of them append the signature.

- [ ] **Step 1: Write the failing tests**

```python
# packages/league-automation/tests/trades/test_format.py
from ultimate_guillotine.trades.format import format_clarification, format_confirmation, format_rescinded, format_updated
from ultimate_guillotine.trades.models import TradeAsset, TradeParty, TradeProposal


def proposal(**overrides) -> TradeProposal:
    base = dict(
        season=2026, effective_week=2, kind="permanent",
        parties=[TradeParty(1, "Max"), TradeParty(2, "Evan")],
        assets=[TradeAsset("player", 2, 1, "p1", "Ja'Marr Chase", None, None, None),
                TradeAsset("player", 1, 2, "p2", "DJ Moore", None, None, None),
                TradeAsset("faab", 1, 2, None, None, 450, "faab", None)],
        rental_return_condition=None, special_terms=[], referenced_trade_code=None,
        source_message_guid="g", evidence_excerpt="e", prompt_version="2026.1", model="m",
    )
    base.update(overrides)
    return TradeProposal(**base)


def test_confirmation_matches_spec_layout() -> None:
    text = format_confirmation("T-2026-014", proposal())
    assert text.splitlines() == [
        "🚨 Trade T-2026-014 logged",
        "Max receives: Ja'Marr Chase",
        "Evan receives: DJ Moore + 450 FAAB",
        "Week 2 · Permanent",
    ]


def test_rental_shows_return_condition_and_special_terms() -> None:
    text = format_confirmation("T-2026-015", proposal(kind="rental", rental_return_condition="returns after Week 4", special_terms=["no gulag protection"]))
    assert "Week 2 · Rental (returns after Week 4)" in text
    assert "Terms: no gulag protection" in text


def test_updated_and_rescinded_and_clarification() -> None:
    assert format_updated("T-2026-014", proposal(), {"assets": []}).startswith("🚨 Trade T-2026-014 updated")
    assert format_rescinded("T-2026-014") == "🚨 Trade T-2026-014 rescinded"
    assert format_clarification("Two players named Mike Williams; which team?") == (
        "🚨 Trade not logged yet: Two players named Mike Williams; which team? "
        "Reply with a corrected 🚨 alert."
    )
```

- [ ] **Step 2: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/trades/test_format.py -v`

- [ ] **Step 3: Implement**

For each party, in party order, list what they receive: player names joined with ` + `, then amounts as `450 FAAB`, `$25`, or `30 draft dollars`, then `protection`/`other` descriptions verbatim. Parties receiving nothing get `receives: nothing`. The footer is `Week {n} · {Kind}` with `Rental (<return condition>)` when a rental has one, `Week ?` when the week is unknown, then `Terms: a; b` when special terms exist. `format_updated` uses the same body with the header `🚨 Trade {code} updated` and, when the previous terms differ in any amount, an extra line `Was: <previous amounts joined by ', '>`. Clarification text is one line as in the test.

- [ ] **Step 4: Run green, lint, commit**

```bash
git add packages/league-automation/src/ultimate_guillotine/trades/format.py packages/league-automation/tests/trades/test_format.py
git commit -m "feat: format trade confirmations and clarifications"
```

### Task 8: Registrar handler, trigger registration, and CLI

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/trades/registrar.py`
- Create: `packages/league-automation/src/ultimate_guillotine/cli/trades.py`
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/main.py` (register the `trades` group)
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/deps.py` (add `build_ai(deps) -> StructuredOutputClient`)
- Modify: `packages/league-automation/src/ultimate_guillotine/listener/run.py` (register `trade_trigger` in `build_processor`)
- Modify: `hermes/guillotine/skills/guillotine-ops/SKILL.md` (document `ug trades list` and `ug trades retry`)
- Create: `packages/league-automation/tests/trades/test_registrar.py`
- Create: `packages/league-automation/tests/cli/test_trades.py`

**Interfaces:**
- Consumes: everything above plus `RunRepository`, `DeliveryService`, `HermesNotifier`, `InboundMessage`, `Trigger`.
- Produces:
  - `TradeRegistrar(settings, conn, ai, delivery, notifier, members_repo, players_repo, trades_repo, runs_repo, clock=...)` with `handle(msg: InboundMessage) -> str` returning one of `created`, `revised`, `duplicate`, `rescinded`, `clarification`, `failed`, `skipped`.
  - `trade_trigger(registrar: TradeRegistrar) -> Trigger` named `trade-registrar`, matching `is_trade_candidate(msg.text) and not msg.is_from_me` (a 🚨 from Ben's own handle still counts when `msg.is_from_me` is true and the text is not signed; implement `matches` as `is_trade_candidate(text) and not is_signed(text)`).
  - `ug trades extract --text "<alert>"` (dry run: prints the resolved proposal as JSON or the clarification reason; no writes, no send), `ug trades list [--limit N]`, `ug trades retry <source_guid>` (re-runs a failed candidate from `private.source_messages.excerpt`), `ug trades replay <xlsx> [--limit N] [--dry-run]` (Task 9).

- [ ] **Step 1: Write the failing handler tests with fakes**

```python
# packages/league-automation/tests/trades/test_registrar.py
from datetime import UTC, datetime

from ultimate_guillotine.ai.openrouter import AIUnavailable, AIUsage
from ultimate_guillotine.config import Settings
from ultimate_guillotine.messages.bluebubbles import InboundMessage
from ultimate_guillotine.sleeper.players import Player
from ultimate_guillotine.trades.models import ExtractedAsset, ExtractedParty, ExtractedTrade
from ultimate_guillotine.trades.registrar import TradeRegistrar, trade_trigger
from ultimate_guillotine.trades.repository import TradeAcceptance
from ultimate_guillotine.trades.resolve import MemberRef

CHAT = "iMessage;+;chat-test"


def msg(text: str, guid: str = "g1", from_me: bool = False) -> InboundMessage:
    return InboundMessage(guid=guid, chat_guid=CHAT, sender_address="+15555550100", text=text,
                          is_from_me=from_me, is_group=True, sent_at=datetime.now(UTC))


def good_extraction() -> ExtractedTrade:
    return ExtractedTrade(
        kind="permanent", parties=[ExtractedParty(name="Member01"), ExtractedParty(name="Member02")],
        assets=[ExtractedAsset(kind="player", from_party="Member01", to_party="Member02", player_name="Player Alpha", amount=None, unit=None, description=None),
                ExtractedAsset(kind="faab", from_party="Member02", to_party="Member01", player_name=None, amount=450, unit="faab", description=None)],
        effective_week=2, rental_return_condition=None, special_terms=[], referenced_trade_code=None, unclear_reason=None,
    )


class FakeAI:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def parse(self, system, user, schema, name):
        if self.error:
            raise self.error
        return self.result, AIUsage("gen", 1, 1, "m")


class FakeDelivery:
    def __init__(self):
        self.sent = []

    def deliver(self, run_id, agent, content):
        self.sent.append((agent, content))
        return type("R", (), {"status": "sent", "outbound_id": 1, "message_guid": "x"})()


class FakeRuns:
    def __init__(self):
        self.reserved, self.finished = [], []

    def reserve(self, agent, trigger, key, invoked_by=None):
        self.reserved.append(key)
        return len(self.reserved)

    def finish(self, run_id, status, output_hash=None, error=None):
        self.finished.append((run_id, status, error))


class FakeTrades:
    def __init__(self, status="created"):
        self.status, self.accepted, self.rescinded = status, [], []

    def accept(self, proposal):
        self.accepted.append(proposal)
        return TradeAcceptance(self.status, 7, "T-2026-001", 1 if self.status != "revised" else 2, {"assets": []} if self.status == "revised" else None)

    def rescind(self, code, source_guid, occurred_at):
        self.rescinded.append(code)
        return True

    def find_by_context(self, key):
        return None


class FakeNotifier:
    def __init__(self):
        self.alerts_sent, self.ops_sent = [], []

    def alerts(self, text):
        self.alerts_sent.append(text); return True

    def ops(self, text):
        self.ops_sent.append(text); return True


class FakeMembers:
    def all_members(self):
        return [MemberRef(1, "Member01", ()), MemberRef(2, "Member02", ())]


class FakePlayers:
    def all_active(self):
        return [Player("p1", "Player Alpha", "WR", "KC", True)]


def build(ai, trades=None, delivery=None):
    settings = Settings(database_url="postgresql://x:y@example.invalid/db", delivery_mode="test",
                        test_chat_guid=CHAT, _env_file=None)
    runs, notifier = FakeRuns(), FakeNotifier()
    reg = TradeRegistrar(settings, None, ai, delivery or FakeDelivery(), notifier, FakeMembers(), FakePlayers(),
                         trades or FakeTrades(), runs, clock=lambda: datetime(2026, 9, 10, tzinfo=UTC))
    return reg, runs, notifier


def test_created_trade_sends_confirmation_and_records_run() -> None:
    delivery = FakeDelivery()
    reg, runs, _ = build(FakeAI(good_extraction()), delivery=delivery)
    assert reg.handle(msg("🚨 Member01 sends Player Alpha to Member02 for 450 FAAB")) == "created"
    assert delivery.sent[0][0] == "trade-registrar"
    assert delivery.sent[0][1].startswith("🚨 Trade T-2026-001 logged")
    assert runs.reserved == ["trade:g1"] and runs.finished[0][1] == "succeeded"


def test_duplicate_sends_nothing_and_marks_run_duplicate() -> None:
    delivery = FakeDelivery()
    reg, runs, _ = build(FakeAI(good_extraction()), trades=FakeTrades("duplicate"), delivery=delivery)
    assert reg.handle(msg("🚨 Member01 sends Player Alpha to Member02 for 450 FAAB")) == "duplicate"
    assert delivery.sent == [] and runs.finished[0][1] == "duplicate"


def test_revised_sends_updated_message() -> None:
    delivery = FakeDelivery()
    reg, _, _ = build(FakeAI(good_extraction()), trades=FakeTrades("revised"), delivery=delivery)
    assert reg.handle(msg("🚨 Member01 sends Player Alpha to Member02 for 500 FAAB")) == "revised"
    assert delivery.sent[0][1].startswith("🚨 Trade T-2026-001 updated")


def test_unclear_sends_clarification_and_logs_no_trade() -> None:
    delivery, trades = FakeDelivery(), FakeTrades()
    unclear = good_extraction().model_copy(update={"kind": "unclear", "unclear_reason": "No counterparty named"})
    reg, runs, _ = build(FakeAI(unclear), trades=trades, delivery=delivery)
    assert reg.handle(msg("🚨 Player Alpha rented for 10")) == "clarification"
    assert trades.accepted == [] and "No counterparty named" in delivery.sent[0][1]
    assert runs.finished[0][1] == "succeeded"


def test_ai_unavailable_alerts_and_fails_run_without_sending() -> None:
    delivery = FakeDelivery()
    reg, runs, notifier = build(FakeAI(error=AIUnavailable("down")), delivery=delivery)
    assert reg.handle(msg("🚨 Member01 sends Player Alpha to Member02")) == "failed"
    assert delivery.sent == [] and runs.finished[0][1] == "failed" and notifier.alerts_sent


def test_rescission_by_code_rescinds_without_calling_the_model() -> None:
    delivery, trades = FakeDelivery(), FakeTrades()
    reg, _, _ = build(FakeAI(error=AssertionError("model must not be called")), trades=trades, delivery=delivery)
    assert reg.handle(msg("🚨 Trade T-2026-001 is rescinded")) == "rescinded"
    assert trades.rescinded == ["T-2026-001"] and delivery.sent[0][1] == "🚨 Trade T-2026-001 rescinded"


def test_trigger_matches_alerts_and_ignores_signed_bot_text() -> None:
    reg, _, _ = build(FakeAI(good_extraction()))
    trigger = trade_trigger(reg)
    assert trigger.name == "trade-registrar"
    assert trigger.matches(msg("🚨 Member01 sends Player Alpha to Member02"))
    assert not trigger.matches(msg("🚨 Trade T-2026-001 logged\nMember02 receives: Player Alpha\n— 🤖 Guillotine Bot", from_me=True))
    assert not trigger.matches(msg("no alert here"))
```

- [ ] **Step 2: Write the failing CLI test**

```python
# packages/league-automation/tests/cli/test_trades.py
import subprocess
import sys


def test_trades_help_lists_commands() -> None:
    result = subprocess.run([sys.executable, "-m", "ultimate_guillotine.cli.main", "trades", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    for name in ("extract", "list", "retry", "replay"):
        assert name in result.stdout
```

- [ ] **Step 3: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/trades/test_registrar.py packages/league-automation/tests/cli/test_trades.py -v`

- [ ] **Step 4: Implement the handler**

`TradeRegistrar.handle(msg)`:

1. `run_id = runs.reserve("trade-registrar", "webhook", f"trade:{msg.guid}")`; if `None`, return `skipped` (already processed).
2. Wrap everything after this in `try/except`; on any unexpected exception `runs.finish(run_id, "failed", error=exc.__class__.__name__)`, `notifier.alerts(f"Trade Registrar failed on a candidate: {exc.__class__.__name__}")`, commit if `conn` is not `None`, and return `failed`.
3. Rescission fast path: if `is_rescission_candidate(msg.text)` and a code matching `T-\d{4}-\d{3}` appears in the text: `trades.rescind(code, msg.guid, msg.sent_at)`; deliver `format_rescinded(code)`; finish `succeeded`; return `rescinded`. If it is a rescission with no code, fall through to extraction and, when `kind == "rescission"`, resolve the target by `trades.find_by_context(trade_context_key(proposal))`; if none, send `format_clarification("Which trade is rescinded? Include its T- code")` and return `clarification`.
4. `extracted, usage = extract_trade(ai, msg.text, season, week_hint, [m.display_name for m in members])` where `season` is the year of `clock()` and `week_hint` is `None` in this plan (the Adjudicator plan adds the current-week lookup). On `AIUnavailable` or `AIInvalidOutput`: finish `failed`, alert, return `failed`.
5. `resolve_extracted(...)` then `validate(...)`; on `Unresolved` deliver `format_clarification(reason)`, finish `succeeded` with `output_hash` of the clarification text, return `clarification`.
6. `acceptance = trades.accept(proposal)`; `duplicate` finishes the run with status `duplicate` and returns without sending; `created` delivers `format_confirmation`; `revised` delivers `format_updated(code, proposal, acceptance.previous_terms)`.
7. Finish `succeeded`, recording `input_version=f"{PROMPT_VERSION}:{usage.model}"` through `runs.finish` (extend `RunRepository.finish` with an optional `input_version` keyword if it lacks one) and `output_hash = sha256(content)`.
8. Commit after each database step when `conn` is provided (`conn.commit()`); the fakes pass `None`.

`trade_trigger` returns `Trigger("trade-registrar", matches, registrar.handle)` where `matches(msg) = is_trade_candidate(msg.text) and not is_signed(msg.text)`; `handle` ignores the returned status.

In `listener/run.py` `build_processor`, after the ping trigger and only when `settings.openrouter_api_key` is set, construct `TradeRegistrar` with `StructuredOutputClient(settings.openrouter_api_key.get_secret_value(), settings.trade_extraction_model, httpx.Client())`, `MemberAliasRepository(conn)`, `PlayerRepository(conn)`, `TradeRepository(conn)`, `CommittingRepo(RunRepository(conn), conn)`, and register `trade_trigger(registrar)`. When the key is missing, log one warning by class name only and post `notifier.ops("Trade Registrar disabled: OPENROUTER_API_KEY not set")` once at startup.

`cli/deps.py` gains `build_ai(deps) -> StructuredOutputClient` raising `SystemExit("OPENROUTER_API_KEY is not set")` when absent. `cli/trades.py` implements `extract` (dry run through `extract_trade` + `resolve_extracted` + `validate`, printing `proposal.model_dump_json(indent=2)` or `clarification: <reason>`; never writes or sends), `list` (prints `code  status  rev  week  parties` per row from `TradeRepository.list_recent`), and `retry` (loads the excerpt for the source guid from `private.source_messages`, rebuilds an `InboundMessage` with `is_from_me=False`, and calls `TradeRegistrar.handle` with idempotency key suffix `:retry:<utc seconds>` by passing `retry=True` to `handle`, which appends the suffix). `replay` is added in Task 9 but the subparser is registered here with a handler that prints `replay is implemented in Task 9` so the help test passes; Task 9 replaces it.

Update `SKILL.md` with the `ug trades list` and `ug trades retry <guid>` commands and a sentence that `ug trades extract --text` is a safe dry run.

- [ ] **Step 5: Run green, lint, restart the listener, commit**

Run: `pnpm test:agents && pnpm lint:agents && launchctl kickstart -k gui/$(id -u)/com.ultimateguillotine.listener && sleep 5 && curl -s http://127.0.0.1:8646/healthz`

Expected: tests PASS; healthz `{"ok":true}`; `~/Library/Logs/UltimateGuillotine/listener.err.log` shows no "Trade Registrar disabled" line (the key is in `.env`).

```bash
git add packages/league-automation hermes/guillotine/skills
git commit -m "feat: register the Trade Registrar trigger and ug trades commands"
```

### Task 9: Historical replay fixture and self-test gate

**Files:**
- Modify: `packages/league-automation/src/ultimate_guillotine/cli/trades.py` (real `replay`)
- Create: `packages/league-automation/tests/cli/test_trades_replay.py`
- Modify: `packages/league-automation/pyproject.toml` (add `openpyxl==3.1.5` to dependencies; verify the current version on PyPI before pinning and use that)
- Modify: `docs/runbooks/mac-mini.md` (add section "8. Trade Registrar rollout")

**Interfaces:**
- Produces: `ug trades replay <xlsx> [--limit N] [--dry-run]` reading the `Terms` and `Parties` columns of `history/contracts/2025-26/all-contracts.xlsx` (sheet `Sheet1`, header row `Date, Week, Terms, Parties...`), prefixing each `Terms` cell with `🚨 ` and running detection, extraction, resolution, and validation with `season=2025`; prints one line per row `row N: created|duplicate|revised|clarification: <reason>|not-a-candidate`, and with `--dry-run` never writes or sends. Without `--dry-run` it writes trades only when `DELIVERY_MODE` is `disabled` or `test` and never sends; it exits 2 in production.

- [ ] **Step 1: Write the failing test**

```python
# packages/league-automation/tests/cli/test_trades_replay.py
from pathlib import Path

from ultimate_guillotine.cli.trades import load_replay_rows


def test_load_replay_rows_reads_terms_and_parties(tmp_path: Path) -> None:
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Date", "Week", "Terms", "Parties"])
    ws.append(["2025-09-07", "Week 1", "Member01 swaps Player Alpha for Player Beta with Member02", "Member01", "Member02"])
    ws.append(["2025-09-08", "Week 1", None, None])
    path = tmp_path / "c.xlsx"; wb.save(path)
    rows = load_replay_rows(path)
    assert rows == [("Week 1", "🚨 Member01 swaps Player Alpha for Player Beta with Member02", ["Member01", "Member02"])]
```

- [ ] **Step 2: Run red, then implement**

`load_replay_rows(path) -> list[tuple[str, str, list[str]]]` skips rows with an empty `Terms` cell and collects every non-empty cell after `Terms` as a party name. The `replay` handler loops rows up to `--limit`, and for each calls the same pipeline as `ug trades extract` (dry run) or `TradeRegistrar.handle` with a synthetic `InboundMessage(guid=f"replay:{sha256(text)[:16]}", ...)` (write mode). Print the per-row line and a final summary `replay: N rows, created X, duplicate Y, clarification Z, not-a-candidate W`.

Run: `pnpm test:agents && pnpm lint:agents`

- [ ] **Step 3: Run the replay in dry-run mode against the real workbook**

Run: `uv run --project packages/league-automation ug trades replay history/contracts/2025-26/all-contracts.xlsx --dry-run --limit 15`

This calls OpenRouter about 15 times (well under a cent). Record in the report how many rows resolved, how many asked for clarification and why. Names that fail to resolve because 2025 members or players differ from the 2026 tables are expected; note them, do not fix them in this task.

- [ ] **Step 4: Self-test gate in the self-test chat**

With `DELIVERY_MODE=test` and the listener restarted:

1. Send `🚨 <Ben> sends Player Alpha to <second handle name>` from the second handle, using two real member display names from `public.members` and a real active player name. Expect a signed `🚨 Trade T-2026-001 logged` reply and a mirror in `#guillotine-feed`.
2. Send the same text again. Expect no reply; `ug ops audit-runs` prints nothing; `select status from private.agent_runs where agent = 'trade-registrar' order by id desc limit 1` is `duplicate`.
3. Send the same trade with a different FAAB amount. Expect `🚨 Trade T-2026-001 updated`.
4. Send `🚨 Trade T-2026-001 is rescinded`. Expect `🚨 Trade T-2026-001 rescinded`.
5. Send `🚨 Player Alpha rented for 10`. Expect a clarification reply and no new trade.
6. Restart the listener between the send and the run completion once (`launchctl kickstart -k` immediately after step 1's send) and confirm exactly one confirmation exists; re-post the webhook payload with the recorded GUID and confirm `duplicate`.
7. `ug trades list` shows the trade with status `rescinded` and revision 2.

Record the outcomes in the new runbook section with the date. Do not record GUIDs or handles. Production promotion (`DELIVERY_MODE=production` and a production target) is a separate, explicit decision by Ben after this gate.

- [ ] **Step 5: Commit**

```bash
git add packages/league-automation docs/runbooks/mac-mini.md uv.lock
git commit -m "feat: add trade replay and record the registrar self-test gate"
```

---

## Self-Review Notes

- Spec coverage: trigger (Task 3, 8), extraction contract (Task 5 prompt and `ExtractedTrade`), validation (Task 4), dedupe by GUID (foundation receipts plus run key `trade:<guid>`), by message fingerprint (foundation `source_messages`), by semantic fingerprint (Task 2 index, Task 6), revisions and `Trade updated` (Tasks 6, 7, 8), rescission (Tasks 3, 6, 8), output format (Task 7), data effects (Task 6 writes revision, trade, league event; run and outbound through the foundation), failure behavior (Task 8: AI unavailable alerts and fails without sending; unknown names ask for clarification; Supabase errors fail the run and the gap-fill re-delivers unseen messages; duplicates send nothing), test and rollout (Task 9). Historical replay is dry-run only because 2025 names do not map to 2026 tables; that is stated in Task 9.
- Names used across tasks: `StructuredOutputClient.parse`, `AIUnavailable`, `AIInvalidOutput`, `AIUsage`, `Player`, `PlayerRepository.all_active`, `MemberRef`, `MemberAliasRepository.all_members`, `Unresolved.reason`, `resolve_extracted`, `validate`, `extract_trade`, `PROMPT_VERSION`, `trade_fingerprint`, `trade_context_key`, `TradeRepository.accept/rescind/find_by_code/find_by_context/list_recent`, `TradeAcceptance`, `format_*`, `TradeRegistrar.handle`, `trade_trigger`.
- The `players` table is public data and read-only for the website, consistent with the foundation's public tables.
- Decisions recorded for the controller: no separate `trade_parties`/`trade_assets` tables (terms live in `trade_revisions.terms` jsonb until the Concierge needs indexed lookups); OpenRouter with `openai/gpt-5-mini` as the default model; `week_hint` is `None` until the Adjudicator supplies the current week.
