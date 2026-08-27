# Automation Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconnect the existing Supabase project and build the secure, resumable Mac mini runtime shared by all league agents.

**Architecture:** Supabase Postgres, Cron, and Queues provide durable state and scheduling. One Python 3.12 package contains domain, data, Sleeper, Messages, and worker modules; the Mac mini runs a `launchd`-supervised queue worker and performs iMessage-only operations.

**Tech Stack:** Python 3.12, uv, Pydantic 2.13.4, psycopg 3.3.4, HTTPX 0.28.1, PostgreSQL 15+, Supabase CLI 2.95.4+, pgmq, pg_cron, pytest 9.1.1, Ruff 0.16.5, macOS Messages AppleScript.

**Spec:** `docs/superpowers/specs/2026-08-27-automation-foundation-design.md`

## Global Constraints

- Supabase is authoritative; do not introduce SQLite or another local state database.
- Store timestamps as UTC `timestamptz`; display rule deadlines in `America/Chicago`.
- The Mac worker uses a dedicated least-privilege Postgres login through Supavisor; its password lives in macOS Keychain, never Git.
- Enable RLS on every table in an exposed schema; public website reads are explicit and read-only.
- Agent delivery modes are exactly `disabled`, `test`, and `production`.
- Test mode can address only the self-test chat; production mode can address only the verified league chat.
- Every bot message ends with `— 🤖 Guillotine Bot`.
- Deterministic code owns scores, ranks, gulag, cuts, and idempotency.
- The 2026 Sleeper league ID is `1389372259260452864` and must report 18 rosters.
- Never print or commit contact details, chat GUIDs, database passwords, API keys, or Messages contents.
- Follow TDD: observe each new test fail before writing its production implementation.

---

### Task 1: Secure configuration and Python workspace

**Files:**
- Create: `pyproject.toml`
- Create: `packages/league-automation/pyproject.toml`
- Create: `packages/league-automation/src/ultimate_guillotine/__init__.py`
- Create: `packages/league-automation/src/ultimate_guillotine/config.py`
- Create: `packages/league-automation/tests/test_config.py`
- Create: `.env.example`
- Modify: `.gitignore`
- Modify: `apps/web/.env.example`
- Modify: `package.json`
- Generate: `uv.lock`

**Interfaces:**
- Consumes: environment and Keychain-injected values only.
- Produces: `Settings`, `DeliveryMode`, `load_settings()`, and root commands `test:agents`, `lint:agents`.

- [ ] **Step 1: Rotate the tracked password before editing the example file**

In the Supabase dashboard, rotate the credential represented by `SupaBasePass` in `apps/web/.env.example`. Do not paste the replacement into the repository. Confirm the old value no longer authenticates, then continue.

- [ ] **Step 2: Write the failing configuration tests**

```python
# packages/league-automation/tests/test_config.py
import pytest
from pydantic import ValidationError

from ultimate_guillotine.config import DeliveryMode, Settings


def test_production_requires_exact_target_identity() -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql://worker:secret@example.invalid/postgres",
            sleeper_league_id="1389372259260452864",
            delivery_mode=DeliveryMode.PRODUCTION,
            test_chat_guid="iMessage;-;test",
        )


def test_test_mode_does_not_require_production_target() -> None:
    settings = Settings(
        database_url="postgresql://worker:secret@example.invalid/postgres",
        sleeper_league_id="1389372259260452864",
        delivery_mode=DeliveryMode.TEST,
        test_chat_guid="iMessage;-;test",
    )
    assert settings.delivery_mode is DeliveryMode.TEST
```

- [ ] **Step 3: Run the tests and verify the import fails**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/test_config.py -v`

Expected: FAIL because `ultimate_guillotine.config` does not exist.

- [ ] **Step 4: Create the workspace and minimal settings implementation**

```toml
# pyproject.toml
[tool.uv.workspace]
members = ["packages/league-automation"]
```

```toml
# packages/league-automation/pyproject.toml
[project]
name = "ultimate-guillotine-automation"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "httpx==0.28.1",
  "psycopg[binary,pool]==3.3.4",
  "pydantic==2.13.4",
  "pydantic-settings==2.15.0",
  "python-dotenv==1.2.3",
]

[dependency-groups]
dev = [
  "pytest==9.1.1",
  "pytest-asyncio==1.4.0",
  "ruff==0.16.5",
]

[build-system]
requires = ["hatchling==1.32.0"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ultimate_guillotine"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 88
target-version = "py312"
```

```python
# packages/league-automation/src/ultimate_guillotine/config.py
from enum import StrEnum

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DeliveryMode(StrEnum):
    DISABLED = "disabled"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    sleeper_league_id: str = "1389372259260452864"
    delivery_mode: DeliveryMode = DeliveryMode.DISABLED
    test_chat_guid: str | None = None
    production_chat_guid: str | None = None
    production_participant_fingerprint: str | None = None
    messages_database_path: str = "~/Library/Messages/chat.db"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.5"

    @model_validator(mode="after")
    def validate_delivery_target(self) -> "Settings":
        if self.delivery_mode is DeliveryMode.TEST and not self.test_chat_guid:
            raise ValueError("test mode requires test_chat_guid")
        if self.delivery_mode is DeliveryMode.PRODUCTION and not (
            self.production_chat_guid and self.production_participant_fingerprint
        ):
            raise ValueError("production mode requires exact target identity")
        return self


def load_settings() -> Settings:
    return Settings()
```

`.env.example` contains empty keys only: `DATABASE_URL`, `SLEEPER_LEAGUE_ID`, `DELIVERY_MODE`, `TEST_CHAT_GUID`, `PRODUCTION_CHAT_GUID`, `PRODUCTION_PARTICIPANT_FINGERPRINT`, `OPENAI_API_KEY`, and `OPENAI_MODEL`. Remove `SupaBasePass` and its value from `apps/web/.env.example`; retain only browser-safe `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` placeholders.

Add `.env`, `.env.*`, and `!*.env.example` rules to `.gitignore`. Add root scripts:

```json
"test:agents": "uv run --project packages/league-automation pytest",
"lint:agents": "uv run --project packages/league-automation ruff check packages/league-automation agents services"
```

- [ ] **Step 5: Lock dependencies and run the tests**

Run: `uv lock && uv sync --all-packages --dev && pnpm test:agents`

Expected: both configuration tests PASS.

- [ ] **Step 6: Verify tracked files contain no credential value**

Run: `git grep -n 'SupaBasePass' -- . ':!docs/superpowers/specs/*' ':!docs/superpowers/plans/*'`

Expected: no matches.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock packages/league-automation .env.example .gitignore apps/web/.env.example package.json
git commit -m "chore: establish automation Python workspace"
```

### Task 2: Reconnect and baseline the existing Supabase project

**Files:**
- Create through CLI: `supabase/config.toml`
- Create through CLI: `supabase/migrations/<generated>_remote_schema.sql`
- Create: `scripts/verify_supabase_baseline.py`
- Create: `packages/league-automation/tests/test_supabase_baseline.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: authenticated Supabase CLI session and the existing project reference.
- Produces: linked local Supabase configuration and a reviewed baseline migration.

- [ ] **Step 1: Initialize and authenticate using CLI discovery**

Run:

```bash
supabase --help
supabase init
supabase login
supabase link
```

Select the existing Ultimate Guillotine project during `supabase link`. Do not pass passwords on the command line or write them to shell history.

- [ ] **Step 2: Pull the remote schema using the installed CLI's documented flags**

Run `supabase db pull --help`, then run `supabase db pull remote_schema` with the flags supported by the installed CLI. The CLI must create the migration filename; do not invent one. Review the generated SQL and confirm whether `player_projections` exists.

- [ ] **Step 3: Write the failing baseline verification test**

```python
# packages/league-automation/tests/test_supabase_baseline.py
from pathlib import Path


def test_supabase_project_has_config_and_baseline() -> None:
    assert Path("supabase/config.toml").is_file()
    migrations = list(Path("supabase/migrations").glob("*_remote_schema.sql"))
    assert len(migrations) == 1
```

- [ ] **Step 4: Reset a local Supabase stack from the pulled baseline**

Run: `supabase start && supabase db reset`

Expected: local database reset exits 0 using the pulled schema.

- [ ] **Step 5: Add a secret-safe runtime verifier**

```python
# scripts/verify_supabase_baseline.py
from pathlib import Path


def main() -> None:
    config = Path("supabase/config.toml")
    migrations = list(Path("supabase/migrations").glob("*_remote_schema.sql"))
    if not config.is_file() or len(migrations) != 1:
        raise SystemExit("Supabase baseline is not linked and unique")
    print("Supabase baseline present")


if __name__ == "__main__":
    main()
```

Document `supabase start`, `supabase db reset`, and the fact that project credentials live outside Git.

- [ ] **Step 6: Verify and commit**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/test_supabase_baseline.py -v && python3 scripts/verify_supabase_baseline.py && supabase migration list --local`

```bash
git add supabase scripts/verify_supabase_baseline.py packages/league-automation/tests/test_supabase_baseline.py README.md
git commit -m "chore: reconnect Supabase project baseline"
```

### Task 3: Create public league schema and RLS

**Files:**
- Create through CLI: `supabase/migrations/<generated>_public_league_schema.sql`
- Create: `supabase/tests/public_league_schema.sql`
- Create: `packages/league-automation/src/ultimate_guillotine/core/models.py`
- Create: `packages/league-automation/tests/core/test_models.py`

**Interfaces:**
- Consumes: pulled Supabase baseline.
- Produces: public league tables and Pydantic models `Season`, `Member`, `Team`, `LeagueEvent`.

- [ ] **Step 1: Write failing model tests**

```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ultimate_guillotine.core.models import LeagueEvent, Season


def test_season_requires_eighteen_rosters() -> None:
    season = Season(year=2026, sleeper_league_id="1389372259260452864", expected_rosters=18)
    assert season.expected_rosters == 18


def test_event_time_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        LeagueEvent(season=2026, event_type="trade", occurred_at=datetime(2026, 9, 1), payload={})
    assert datetime.now(UTC).tzinfo is UTC
```

- [ ] **Step 2: Run the model tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/core/test_models.py -v`

Expected: FAIL because `core.models` is missing.

- [ ] **Step 3: Implement the domain models**

Use frozen Pydantic models with `AwareDatetime` and these exact fields:

```python
class Season(BaseModel, frozen=True):
    year: int
    sleeper_league_id: str
    expected_rosters: int = 18
    rules_version: str = "2026.1"


class LeagueEvent(BaseModel, frozen=True):
    season: int
    week: int | None = None
    event_type: str
    occurred_at: AwareDatetime
    payload: dict[str, object]
    idempotency_key: str | None = None
```

Also define `Member(id: int | None, display_name: str)` and `Team(id, season, member_id, sleeper_user_id, sleeper_roster_id, team_name)`.

- [ ] **Step 4: Create the migration through the CLI**

Run: `supabase migration new public_league_schema`

In the generated file, create lowercase tables `seasons`, `members`, `teams`, `weekly_results`, `league_events`, `trades`, `trade_revisions`, `survival_snapshots`, and `recaps` using `bigint generated always as identity` primary keys, `timestamptz`, `jsonb`, explicit check constraints, and indexed foreign keys. Add unique constraints for `(year)`, `(season_id, sleeper_roster_id)`, `league_events.idempotency_key`, and each table's natural version key.

Enable RLS on all nine tables. Grant `anon` and `authenticated` `select` only. Create select policies with `using (true)` for public league rows; do not grant insert, update, or delete. Seed season 2026 with Sleeper league `1389372259260452864`, expected roster count 18, and rules version `2026.1` using `on conflict (year) do update`.

- [ ] **Step 5: Add database assertions**

```sql
-- supabase/tests/public_league_schema.sql
begin;
select plan(4);
select has_table('public', 'seasons');
select has_table('public', 'league_events');
select policies_are('public', 'seasons', array['Public league seasons are readable']);
select col_is_pk('public', 'seasons', 'id');
select * from finish();
rollback;
```

- [ ] **Step 6: Verify locally and commit**

Run: `supabase db reset && supabase test db && pnpm test:agents`

```bash
git add supabase packages/league-automation/src/ultimate_guillotine/core packages/league-automation/tests/core
git commit -m "feat: add public league data model"
```

### Task 4: Create private operational schema, queue, and worker role

**Files:**
- Create through CLI: `supabase/migrations/<generated>_private_automation_schema.sql`
- Create: `supabase/tests/private_automation_schema.sql`
- Create: `scripts/configure_worker_role.sql.example`

**Interfaces:**
- Consumes: public league schema.
- Produces: private operational tables, `agent_jobs` queue, and least-privilege `automation_worker` role.

- [ ] **Step 1: Create the migration through the CLI**

Run: `supabase migration new private_automation_schema`

- [ ] **Step 2: Add the private schema and operational tables**

Create schema `private`, revoke all from `public`, `anon`, and `authenticated`, and create:

- `private.member_contacts`
- `private.delivery_targets`
- `private.source_cursors`
- `private.source_messages`
- `private.agent_runs`
- `private.outbound_messages`
- `private.projection_snapshots`
- `private.knowledge_sources`
- `private.worker_heartbeats`

Use identity primary keys, indexed foreign keys, `timestamptz`, and check constraints matching the spec. Required unique keys are `(source_name, chat_guid_hash)` for cursors, `(source_name, source_guid)` and `(chat_guid_hash, content_fingerprint, sent_at)` for source messages, `agent_runs.idempotency_key`, and `(delivery_target_id, content_hash, reserved_at)` for outbound records.

Store exact chat GUIDs only in `private.delivery_targets`. Store no database password or AI key in any table.

- [ ] **Step 3: Enable durable Queue support and grants**

Add:

```sql
create extension if not exists pgmq;
select pgmq.create('agent_jobs');

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'automation_worker') then
    create role automation_worker nologin;
  end if;
end $$;

grant usage on schema private, pgmq to automation_worker;
grant select, insert, update on all tables in schema private to automation_worker;
grant usage, select on all sequences in schema private to automation_worker;
alter default privileges in schema private grant select, insert, update on tables to automation_worker;
alter default privileges in schema private grant usage, select on sequences to automation_worker;
grant select, insert, update on public.seasons, public.members, public.teams,
  public.weekly_results, public.league_events, public.trades,
  public.trade_revisions, public.survival_snapshots, public.recaps
  to automation_worker;
grant usage, select on all sequences in schema public to automation_worker;
grant execute on function pgmq.send(text, jsonb, integer) to automation_worker;
```

Grant only the exact `pgmq.read`, `pgmq.archive`, and `pgmq.delete` overloads reported by `\df pgmq.*` in the local database. Do not grant queue creation or dropping.

- [ ] **Step 4: Add worker-login setup example without a password**

```sql
-- scripts/configure_worker_role.sql.example
-- Run interactively with a newly generated password; never commit the substitution.
create role ultimate_guillotine_mac login password :'worker_password';
grant automation_worker to ultimate_guillotine_mac;
```

- [ ] **Step 5: Add database assertions**

```sql
begin;
select plan(5);
select has_schema('private');
select has_table('private', 'agent_runs');
select has_table('private', 'outbound_messages');
select has_role('automation_worker');
select is_empty($$select 1 from information_schema.role_table_grants where grantee = 'anon' and table_schema = 'private'$$);
select * from finish();
rollback;
```

- [ ] **Step 6: Verify advisors and commit**

Run: `supabase db reset && supabase test db && supabase db advisors`

Expected: tests PASS and no unaddressed security advisor findings from the new schema.

```bash
git add supabase scripts/configure_worker_role.sql.example
git commit -m "feat: add private automation schema and queue"
```

### Task 5: Implement Sleeper client and seasonal synchronization

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/sleeper/client.py`
- Create: `packages/league-automation/src/ultimate_guillotine/sleeper/models.py`
- Create: `packages/league-automation/src/ultimate_guillotine/sleeper/sync.py`
- Create: `packages/league-automation/tests/sleeper/test_client.py`
- Create: `packages/league-automation/tests/fixtures/sleeper/league_2026.json`
- Create: `packages/league-automation/tests/fixtures/sleeper/rosters_2026.json`

**Interfaces:**
- Consumes: `Settings.sleeper_league_id`, official Sleeper read-only endpoints.
- Produces: `SleeperClient`, `SleeperLeague`, `SleeperRoster`, `sync_season(client, repository, year)`.

- [ ] **Step 1: Save minimal anonymized fixtures and write failing tests**

```python
async def test_get_league_requires_expected_roster_count(fake_transport) -> None:
    client = SleeperClient(transport=fake_transport)
    league = await client.get_league("1389372259260452864")
    assert league.season == "2026"
    assert league.total_rosters == 18


async def test_sync_rejects_wrong_league_size(fake_repository, fake_client) -> None:
    fake_client.league.total_rosters = 12
    with pytest.raises(ValueError, match="expected 18 rosters"):
        await sync_season(fake_client, fake_repository, 2026)
```

- [ ] **Step 2: Run tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper -v`

Expected: FAIL because Sleeper modules are absent.

- [ ] **Step 3: Implement typed API methods**

`SleeperClient` uses one `httpx.AsyncClient(base_url="https://api.sleeper.app/v1", timeout=10.0)` and implements `get_league`, `get_users`, `get_rosters`, `get_matchups(week)`, `get_transactions(week)`, and `get_nfl_state`. Call `response.raise_for_status()` and parse Pydantic models. Do not implement Sleeper writes.

- [ ] **Step 4: Implement idempotent seasonal sync**

`sync_season` validates season `2026`, 18 rosters, and expected league ID, then performs atomic `insert ... on conflict do update` statements for `seasons`, `members`, and `teams`. It records source fetch timestamps and never marks a team eliminated.

- [ ] **Step 5: Verify and commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation/src/ultimate_guillotine/sleeper packages/league-automation/tests/sleeper
git commit -m "feat: synchronize 2026 Sleeper league"
```

### Task 6: Implement read-only Messages ingestion and allowlisted sending

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/messages/models.py`
- Create: `packages/league-automation/src/ultimate_guillotine/messages/reader.py`
- Create: `packages/league-automation/src/ultimate_guillotine/messages/sender.py`
- Create: `packages/league-automation/src/ultimate_guillotine/messages/targets.py`
- Create: `packages/league-automation/tests/messages/test_reader.py`
- Create: `packages/league-automation/tests/messages/test_sender.py`
- Create: `packages/league-automation/tests/fixtures/messages/schema.sql`

**Interfaces:**
- Consumes: read-only Messages database path and `DeliveryTarget` records.
- Produces: `MessageEnvelope`, `MessagesReader.read_after()`, `MessagesSender.send()`, `verify_target()`.

- [ ] **Step 1: Write failing reader and sender tests**

```python
def test_reader_returns_only_allowlisted_chat(message_database) -> None:
    reader = MessagesReader(message_database)
    rows = reader.read_after(row_id=0, allowed_chat_guids={"iMessage;+;league"})
    assert [row.guid for row in rows] == ["message-2"]


def test_production_sender_rejects_participant_change(fake_runner) -> None:
    target = DeliveryTarget(
        mode=DeliveryMode.PRODUCTION,
        chat_guid="iMessage;+;league",
        participant_fingerprint="expected",
    )
    sender = MessagesSender(fake_runner)
    with pytest.raises(TargetMismatch):
        sender.send(target, "hello", observed_participant_fingerprint="changed")
    assert fake_runner.calls == []
```

- [ ] **Step 2: Run the tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/messages -v`

Expected: FAIL because Messages modules are absent.

- [ ] **Step 3: Implement read-only ingestion**

Open SQLite with URI `file:<expanded path>?mode=ro` and `uri=True`. Query `message`, `chat_message_join`, `chat`, and `handle` for rows greater than the stored row ID and chats in the explicit allowlist. Convert Apple's nanosecond epoch to aware UTC. Return only GUID, row ID, chat GUID, sender handle, direction, sent time, text, and message association fields.

Never copy the Messages database or write to it. Hash sender handles before persistence unless a private member alias mapping requires the exact value.

- [ ] **Step 4: Implement target verification and AppleScript send**

`MessagesSender.send()` appends the signature once, verifies mode, chat GUID, and participant fingerprint, then invokes `osascript` with the message passed as an argument rather than interpolated into script source:

```applescript
on run argv
  set targetId to item 1 of argv
  set bodyText to item 2 of argv
  tell application "Messages"
    set targetChat to first chat whose id is targetId
    send bodyText to targetChat
  end tell
end run
```

Use `subprocess.run([...], check=True, capture_output=True, text=True, timeout=15)` and never log the message body on failure.

- [ ] **Step 5: Verify on fixtures and commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation/src/ultimate_guillotine/messages packages/league-automation/tests/messages
git commit -m "feat: add safe Messages gateway"
```

### Task 7: Implement queue worker, idempotency, and reconciliation

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/data/database.py`
- Create: `packages/league-automation/src/ultimate_guillotine/runtime/jobs.py`
- Create: `packages/league-automation/src/ultimate_guillotine/runtime/worker.py`
- Create: `packages/league-automation/src/ultimate_guillotine/runtime/delivery.py`
- Create: `packages/league-automation/tests/runtime/test_worker.py`
- Create: `packages/league-automation/tests/runtime/test_delivery.py`
- Create: `services/mac-worker/main.py`

**Interfaces:**
- Consumes: pgmq `agent_jobs`, agent registry, Messages reader/sender.
- Produces: `JobEnvelope`, `JobHandler`, `Worker.run_once()`, `DeliveryCoordinator.deliver()`.

- [ ] **Step 1: Write failing effectively-once tests**

```python
async def test_duplicate_job_runs_handler_once(fake_queue, fake_runs, handler) -> None:
    fake_queue.messages = [job("same-key"), job("same-key")]
    worker = Worker(fake_queue, fake_runs, {"test": handler})
    await worker.run_once()
    await worker.run_once()
    assert handler.calls == 1


async def test_ambiguous_send_reconciles_before_retry(coordinator, sent_reader, sender) -> None:
    sent_reader.add_recent(content_hash="abc", target_id=7)
    result = await coordinator.deliver(reservation(content_hash="abc", target_id=7))
    assert result.status == "reconciled"
    assert sender.calls == []
```

- [ ] **Step 2: Run runtime tests red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/runtime -v`

- [ ] **Step 3: Implement database pool and queue lease**

Create a `psycopg_pool.AsyncConnectionPool` with minimum 1 and maximum 4 connections. `claim()` uses `pgmq.read('agent_jobs', visibility_timeout_seconds, 1)`. `archive()` and `delete()` use the exact installed pgmq signatures. `agent_runs.idempotency_key` is reserved with `insert ... on conflict do nothing returning id`; a missing return marks a duplicate.

- [ ] **Step 4: Implement delivery state machine**

Allowed states are `reserved`, `sending`, `sent`, `reconciled`, and `failed`. Reserve content before sending. On retry from `sending`, search recent sent Messages in the exact chat for normalized signed content. If found, mark `reconciled`; otherwise retry only after the lease expires.

- [ ] **Step 5: Implement worker entry point and heartbeat**

`Worker.run_once()` claims one job, reserves its idempotency key, dispatches by `agent_name`, records success/failure, and archives only successful or duplicate queue messages. The service entry point loads Keychain-injected environment, starts the connection pool, writes a heartbeat every 60 seconds, and polls with a maximum idle delay of 5 seconds.

- [ ] **Step 6: Verify crash replay and commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation/src/ultimate_guillotine/data packages/league-automation/src/ultimate_guillotine/runtime packages/league-automation/tests/runtime services/mac-worker
git commit -m "feat: add resumable Mac worker runtime"
```

### Task 8: Install launchd service and complete the self-test delivery gate

**Files:**
- Create: `scripts/mac-mini/com.ultimateguillotine.worker.plist.template`
- Create: `scripts/mac-mini/install_worker.sh`
- Create: `scripts/mac-mini/doctor.py`
- Create: `scripts/mac-mini/send_self_test.py`
- Create: `docs/runbooks/mac-mini-worker.md`
- Create: `packages/league-automation/tests/integration/test_self_test_delivery.py`

**Interfaces:**
- Consumes: built worker, Keychain configuration, self-test chat GUID.
- Produces: installed `launchd` service, health report, verified test-mode iMessage delivery.

- [ ] **Step 1: Write failing doctor tests**

```python
def test_doctor_fails_when_delivery_mode_is_production_without_target(monkeypatch) -> None:
    monkeypatch.setenv("DELIVERY_MODE", "production")
    monkeypatch.delenv("PRODUCTION_CHAT_GUID", raising=False)
    assert doctor() == ["production target identity is incomplete"]
```

- [ ] **Step 2: Implement doctor and installation scripts**

The doctor checks Python 3.12, `uv`, Supabase connectivity, Queue access, Messages database readability, Automation permission, Full Disk Access, selected delivery mode, exact target identity, and worker heartbeat. It prints statuses but redacts values.

The plist runs `uv run --project packages/league-automation python services/mac-worker/main.py`, sets the repository working directory, uses `KeepAlive` and `RunAtLoad`, and writes logs under `~/Library/Logs/UltimateGuillotine/` without message bodies.

- [ ] **Step 3: Test the launchd template and doctor**

Run: `plutil -lint scripts/mac-mini/com.ultimateguillotine.worker.plist.template && uv run --project packages/league-automation pytest packages/league-automation/tests/integration/test_self_test_delivery.py -v`

- [ ] **Step 4: Install on the Mac mini in test mode**

Run the installer on the Mac mini, grant Messages Automation and Full Disk Access, store the worker database password and chat identifiers in Keychain, then run `python3 scripts/mac-mini/doctor.py`.

Expected: every required check reports PASS and delivery mode reports `test`.

- [ ] **Step 5: Exercise the end-to-end self-test**

`send_self_test.py` enqueues one uniquely identified test job. Verify one and only one signed message arrives in the self-test chat. Restart the worker and replay the same idempotency key; verify no second message arrives.

- [ ] **Step 6: Run the foundation verification suite**

Run:

```bash
pnpm test:agents
pnpm lint:agents
supabase db reset
supabase test db
supabase db advisors
pnpm build
git diff --check
```

Expected: all tests and build exit 0; no new security advisor finding is left unexplained.

- [ ] **Step 7: Commit**

```bash
git add scripts/mac-mini docs/runbooks/mac-mini-worker.md packages/league-automation/tests/integration
git commit -m "ops: install Mac mini automation worker"
```
