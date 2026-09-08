# Automation Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the shared league automation platform: Supabase schema, Sleeper sync, BlueBubbles iMessage delivery with effectively-once semantics, a webhook listener, a dedicated Hermes profile with scheduled ops jobs, and Discord ops channels, ending with Gate 0 passed on the Mac mini.

**Architecture:** One Python package (`ultimate_guillotine`) holds domain models, Postgres repositories, the Sleeper adapter, the BlueBubbles client, the delivery layer, the inbound processor, and a `ug` command-line tool. Hermes cron on a `guillotine` profile runs `ug` commands on schedule and delivers their output to Discord. A `launchd`-supervised FastAPI listener receives BlueBubbles webhooks and runs event-driven agents inline. Supabase is the only durable state.

**Tech Stack:** Python 3.12 (installed by uv), uv 0.11.1, Pydantic 2.13.5, pydantic-settings 2.15.0, psycopg 3.3.5, HTTPX 0.28.1, FastAPI 0.141.1, Uvicorn 0.52.4, PyYAML 6.0.3, pytest 9.1.1, respx 0.23.1, Ruff 0.16.6, Supabase CLI 2.84.2 with Docker Desktop, Hermes Agent v0.17.0, BlueBubbles Server 1.9+.

**Spec:** `docs/superpowers/specs/2026-08-27-automation-foundation-design.md` (revision 2026-09-08)

## Global Constraints

- Supabase is authoritative; do not introduce SQLite or another local state database.
- Supabase Cron and Supabase Queue are not used. Do not enable `pg_cron` or `pgmq`.
- Store timestamps as UTC `timestamptz`; display rule deadlines in `America/Chicago`.
- Agent delivery modes are exactly `disabled`, `test`, and `production`.
- Test mode can address only the self-test chat; production mode can address only the verified league chat. Never fall back from test to production.
- Every bot message ends with `— 🤖 Guillotine Bot`, appended exactly once.
- The delivery layer in `ultimate_guillotine.messages.delivery` is the only code that calls the BlueBubbles send endpoint. Hermes's BlueBubbles adapter stays disabled in every profile.
- Deterministic code owns scores, ranks, gulag, cuts, and idempotency. This plan contains no language model calls.
- The 2026 Sleeper league ID is `1389372259260452864` and must report 18 rosters.
- Never print, log, or commit contact details, chat GUIDs, the BlueBubbles password, database passwords, bot tokens, or message bodies. Tests use fake GUIDs such as `iMessage;+;chat-test`.
- Secrets live in ignored `.env` files or macOS Keychain. The Hermes `guillotine` profile's Discord token is pasted by Ben into that profile's `.env`; no task reads or moves it.
- Use `uv run --project packages/league-automation` for every Python command. Follow TDD: watch each new test fail before writing production code.
- Commit after each task with a conventional message ending in `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Verified External Interfaces

These were read from the BlueBubbles server source and the installed Hermes CLI on 2026-09-08. Do not substitute remembered variants.

BlueBubbles REST, all requests authenticated with `?password=<server password>`:

| Purpose | Method and path | Notes |
| --- | --- | --- |
| Liveness | `GET /api/v1/ping` | `data == "pong"` |
| Server info | `GET /api/v1/server/info` | `data.private_api` reports helper state |
| Chat with participants | `GET /api/v1/chat/{guid}?with=participants` | `data.participants[].address` |
| Messages in a chat | `GET /api/v1/chat/{guid}/message?after=<unix ms>&sort=ASC&limit=100&with=handle` | `data[]` each has `guid`, `text`, `isFromMe`, `dateCreated` (ms), `handle.address` |
| Send text | `POST /api/v1/message/text` body `{"chatGuid","tempGuid","message"}` | response `data.guid` is the sent message GUID; omit `method` to use the standard AppleScript send |
| List webhooks | `GET /api/v1/webhook` | `data[]` with `id`, `url`, `events` |
| Create webhook | `POST /api/v1/webhook` body `{"url","events":["new-message"]}` | |
| Webhook payload | `POST <url>` body `{"type":"new-message","data":{...}}` | `data.guid`, `data.text`, `data.isFromMe`, `data.isGroup`, `data.dateCreated`, `data.handle.address`, `data.chats[0].guid` |

Hermes CLI (v0.17.0), run with `HERMES_HOME=$HOME/.hermes/profiles/guillotine` for the league profile:

- `hermes profile create guillotine --no-skills --description "..."`
- `hermes cron create "<schedule>" --name <name> --script <file under $HERMES_HOME/scripts/> --no-agent --deliver "discord:#channel"`
- `hermes cron edit <job_id> --schedule ... --script ... --deliver ...`
- `hermes cron list`, `hermes cron run <id>`, `hermes cron status`
- `hermes send --to "discord:#channel" --quiet "<text>"` reuses the profile's Discord credentials, no LLM.
- `hermes gateway install` writes and loads a launchd plist for the profile's gateway.
- Job state file: `$HERMES_HOME/cron/jobs.json`, a JSON object whose job records carry `id` and `name`.

## File Structure

```text
pyproject.toml                                   # uv workspace root
packages/league-automation/
  pyproject.toml
  src/ultimate_guillotine/
    __init__.py
    config.py                                    # Settings, DeliveryMode, load_settings
    core/models.py                               # Season, Member, Team, LeagueEvent
    core/signature.py                            # BOT_SIGNATURE, sign(), is_signed()
    data/database.py                             # connect(settings)
    data/repositories.py                         # one small class per private table
    sleeper/client.py, models.py, sync.py        # read-only Sleeper adapter
    messages/bluebubbles.py                      # BlueBubblesClient, InboundMessage, parse_webhook
    messages/fingerprint.py                      # participant_fingerprint()
    messages/delivery.py                         # DeliveryService, DeliveryTarget, TargetMismatch
    ops/notify.py                                # HermesNotifier (hermes send wrapper)
    ops/health.py                                # health checks and run audit
    listener/processing.py                       # InboundProcessor, TriggerRegistry
    listener/app.py                              # create_app() FastAPI factory
    cli/main.py                                  # `ug` argparse entry point
  tests/                                         # mirrors src layout
services/webhook-listener/main.py                # uvicorn launcher
supabase/config.toml, migrations/, tests/         # CLI-managed
hermes/guillotine/
  SOUL.md
  cron.yaml
  register_cron.py                               # cron.yaml -> hermes cron create/edit
  install.sh
  scripts/*.sh.template                          # rendered into the profile's scripts dir
  skills/guillotine-ops/SKILL.md
scripts/mac-mini/
  com.ultimateguillotine.listener.plist.template
  install_listener.sh
docs/runbooks/mac-mini.md
```

---

### Task 1: Configuration and Python workspace

**Files:**
- Create: `pyproject.toml`
- Create: `packages/league-automation/pyproject.toml`
- Create: `packages/league-automation/src/ultimate_guillotine/__init__.py`
- Create: `packages/league-automation/src/ultimate_guillotine/config.py`
- Create: `packages/league-automation/src/ultimate_guillotine/core/__init__.py`
- Create: `packages/league-automation/src/ultimate_guillotine/core/signature.py`
- Create: `packages/league-automation/tests/test_config.py`
- Create: `packages/league-automation/tests/core/test_signature.py`
- Create: `.env.example`
- Modify: `.gitignore`
- Modify: `apps/web/.env.example`
- Modify: `package.json`
- Generate: `uv.lock`

**Interfaces:**
- Consumes: environment variables only.
- Produces: `Settings`, `DeliveryMode`, `load_settings()`, `BOT_SIGNATURE`, `sign(text) -> str`, `is_signed(text) -> bool`.

- [ ] **Step 1: Install Python 3.12 through uv**

Run: `uv python install 3.12 && uv python find 3.12`

Expected: a path to a CPython 3.12 interpreter.

- [ ] **Step 2: Rotate the tracked password**

In the Supabase dashboard, rotate the credential named `SupaBasePass` in `apps/web/.env.example`. Do not paste the replacement anywhere in the repository. This is the old, unreachable project; rotating is still required because the value is public in git history.

- [ ] **Step 3: Write the failing tests**

```python
# packages/league-automation/tests/test_config.py
import pytest
from pydantic import ValidationError

from ultimate_guillotine.config import DeliveryMode, Settings

BASE = {"database_url": "postgresql://worker:secret@example.invalid/postgres"}


def test_production_requires_exact_target_identity() -> None:
    with pytest.raises(ValidationError):
        Settings(**BASE, delivery_mode=DeliveryMode.PRODUCTION, test_chat_guid="iMessage;+;chat-test")


def test_test_mode_requires_test_chat() -> None:
    with pytest.raises(ValidationError):
        Settings(**BASE, delivery_mode=DeliveryMode.TEST)


def test_disabled_needs_no_targets() -> None:
    settings = Settings(**BASE)
    assert settings.delivery_mode is DeliveryMode.DISABLED
    assert settings.webhook_listen_host == "127.0.0.1"


def test_secrets_do_not_repr() -> None:
    settings = Settings(**BASE, bluebubbles_password="hunter2")
    assert "hunter2" not in repr(settings)
```

```python
# packages/league-automation/tests/core/test_signature.py
from ultimate_guillotine.core.signature import BOT_SIGNATURE, is_signed, sign


def test_sign_appends_once() -> None:
    once = sign("hello")
    assert once == f"hello\n{BOT_SIGNATURE}"
    assert sign(once) == once


def test_is_signed() -> None:
    assert is_signed(sign("x"))
    assert not is_signed("x")
```

- [ ] **Step 4: Run the tests and verify they fail on import**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests -v`

Expected: errors because the package does not exist yet.

- [ ] **Step 5: Create the workspace and implementation**

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
  "fastapi==0.141.1",
  "httpx==0.28.1",
  "psycopg[binary,pool]==3.3.5",
  "pydantic==2.13.5",
  "pydantic-settings==2.15.0",
  "python-dotenv==1.2.3",
  "pyyaml==6.0.3",
  "uvicorn==0.52.4",
]

[project.scripts]
ug = "ultimate_guillotine.cli.main:main"

[dependency-groups]
dev = [
  "pytest==9.1.1",
  "respx==0.23.1",
  "ruff==0.16.6",
]

[build-system]
requires = ["hatchling==1.32.0"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ultimate_guillotine"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
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

    database_url: SecretStr
    sleeper_league_id: str = "1389372259260452864"
    delivery_mode: DeliveryMode = DeliveryMode.DISABLED
    test_chat_guid: str | None = None
    production_chat_guid: str | None = None
    production_participant_fingerprint: str | None = None
    bluebubbles_server_url: str = "http://127.0.0.1:1234"
    bluebubbles_password: SecretStr | None = None
    webhook_listen_host: str = "127.0.0.1"
    webhook_listen_port: int = 8646
    webhook_password: SecretStr | None = None
    hermes_profile_home: str = "~/.hermes/profiles/guillotine"
    discord_ops_channel: str = "#guillotine-ops"
    discord_feed_channel: str = "#guillotine-feed"
    discord_drafts_channel: str = "#guillotine-drafts"
    discord_alerts_channel: str = "#guillotine-alerts"

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

```python
# packages/league-automation/src/ultimate_guillotine/core/signature.py
BOT_SIGNATURE = "— 🤖 Guillotine Bot"


def is_signed(text: str) -> bool:
    return text.rstrip().endswith(BOT_SIGNATURE)


def sign(text: str) -> str:
    body = text.rstrip()
    return body if is_signed(body) else f"{body}\n{BOT_SIGNATURE}"
```

`.env.example` lists every `Settings` field name in upper case with empty values. Replace `apps/web/.env.example` content with empty `VITE_SUPABASE_URL=` and `VITE_SUPABASE_ANON_KEY=` lines only. Add `.env`, `.env.*`, and `!*.env.example` to `.gitignore`. Add root `package.json` scripts:

```json
"test:agents": "uv run --project packages/league-automation pytest",
"lint:agents": "uv run --project packages/league-automation ruff check packages/league-automation services hermes"
```

- [ ] **Step 6: Lock, sync, and run green**

Run: `uv lock && uv sync --all-packages --dev && pnpm test:agents && pnpm lint:agents`

Expected: 6 tests PASS, lint clean.

- [ ] **Step 7: Verify no credential value is tracked**

Run: `git grep -n 'SupaBasePass' -- . ':!docs/superpowers/**'`

Expected: no matches.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock packages/league-automation .env.example .gitignore apps/web/.env.example package.json
git commit -m "feat: add league automation workspace and settings"
```

### Task 2: Local Supabase project and baseline

**Files:**
- Create through CLI: `supabase/config.toml`
- Create: `supabase/.gitignore` (CLI-generated)
- Create: `scripts/verify_supabase_baseline.py`
- Create: `packages/league-automation/tests/test_supabase_baseline.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: Docker Desktop and the Supabase CLI.
- Produces: a runnable local Supabase stack; `TEST_DATABASE_URL` convention for repository tests.

- [ ] **Step 1: Write the failing baseline test**

```python
# packages/league-automation/tests/test_supabase_baseline.py
from pathlib import Path


def test_supabase_config_is_present() -> None:
    assert Path("supabase/config.toml").is_file()
    assert Path("supabase/migrations").is_dir()
```

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/test_supabase_baseline.py -v`

Expected: FAIL, no `supabase/` directory.

- [ ] **Step 2: Initialize the local project**

Run:

```bash
open -a Docker
supabase init
mkdir -p supabase/migrations
supabase start
supabase status
```

Expected: `supabase status` prints a local `DB URL`. Do not run `supabase link` in this task; the hosted project is linked in Task 12 once Ben has created it under his personal account.

- [ ] **Step 3: Add the secret-safe verifier**

```python
# scripts/verify_supabase_baseline.py
from pathlib import Path


def main() -> None:
    if not Path("supabase/config.toml").is_file():
        raise SystemExit("supabase/config.toml missing: run `supabase init`")
    print("Supabase baseline present")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Document the local stack**

In `README.md`, add a "League automation" section: `open -a Docker`, `supabase start`, `supabase db reset`, `supabase test db`, and the rule that repository tests read `TEST_DATABASE_URL` from the environment and skip when it is unset. State that project credentials live outside Git.

- [ ] **Step 5: Verify and commit**

Run: `pnpm test:agents && python3 scripts/verify_supabase_baseline.py`

```bash
git add supabase scripts/verify_supabase_baseline.py packages/league-automation/tests/test_supabase_baseline.py README.md
git commit -m "chore: initialize local Supabase stack"
```

### Task 3: Public league schema, RLS, and domain models

**Files:**
- Create through CLI: `supabase/migrations/<generated>_public_league_schema.sql`
- Create: `supabase/tests/public_league_schema.sql`
- Create: `packages/league-automation/src/ultimate_guillotine/core/models.py`
- Create: `packages/league-automation/tests/core/test_models.py`

**Interfaces:**
- Consumes: local Supabase stack.
- Produces: nine public tables; Pydantic models `Season`, `Member`, `Team`, `LeagueEvent`.

- [ ] **Step 1: Write failing model tests**

```python
# packages/league-automation/tests/core/test_models.py
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ultimate_guillotine.core.models import LeagueEvent, Season, Team


def test_season_defaults() -> None:
    season = Season(year=2026, sleeper_league_id="1389372259260452864")
    assert season.expected_rosters == 18
    assert season.rules_version == "2026.1"


def test_event_time_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        LeagueEvent(season=2026, event_type="trade", occurred_at=datetime(2026, 9, 1), payload={})
    LeagueEvent(season=2026, event_type="trade", occurred_at=datetime.now(UTC), payload={})


def test_models_are_frozen() -> None:
    team = Team(id=None, season=2026, member_id=1, sleeper_user_id="u1", sleeper_roster_id=3, team_name="Blades")
    with pytest.raises(ValidationError):
        team.team_name = "Other"
```

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/core/test_models.py -v`

Expected: FAIL, `core.models` missing.

- [ ] **Step 2: Implement the models**

```python
# packages/league-automation/src/ultimate_guillotine/core/models.py
from pydantic import AwareDatetime, BaseModel


class Season(BaseModel, frozen=True):
    year: int
    sleeper_league_id: str
    expected_rosters: int = 18
    rules_version: str = "2026.1"


class Member(BaseModel, frozen=True):
    id: int | None
    display_name: str


class Team(BaseModel, frozen=True):
    id: int | None
    season: int
    member_id: int
    sleeper_user_id: str
    sleeper_roster_id: int
    team_name: str


class LeagueEvent(BaseModel, frozen=True):
    season: int
    week: int | None = None
    event_type: str
    occurred_at: AwareDatetime
    payload: dict[str, object]
    idempotency_key: str | None = None
```

- [ ] **Step 3: Create the migration**

Run: `supabase migration new public_league_schema`

In the generated file create these tables, each with `id bigint generated always as identity primary key`, `created_at timestamptz not null default now()`, and the listed columns:

- `seasons`: `year int not null unique`, `sleeper_league_id text not null`, `phase text not null default 'preseason'`, `rules_version text not null`, `expected_rosters int not null default 18`.
- `members`: `display_name text not null unique`.
- `teams`: `season_id bigint not null references seasons(id)`, `member_id bigint not null references members(id)`, `sleeper_user_id text not null`, `sleeper_roster_id int not null`, `team_name text not null`, unique `(season_id, sleeper_roster_id)`, unique `(season_id, member_id)`.
- `weekly_results`: `season_id`, `week int not null`, `team_id bigint not null references teams(id)`, `points numeric(8,2) not null`, `state_version int not null default 1`, `is_final boolean not null default false`, unique `(season_id, week, team_id, state_version)`.
- `league_events`: `season_id`, `week int`, `event_type text not null`, `occurred_at timestamptz not null`, `payload jsonb not null default '{}'`, `idempotency_key text unique`.
- `trades`: `season_id`, `trade_code text not null unique` (format `T-2026-001`), `current_revision_id bigint`, `status text not null default 'accepted' check (status in ('accepted','rescinded'))`.
- `trade_revisions`: `trade_id bigint not null references trades(id)`, `revision int not null`, `terms jsonb not null`, `source_message_guid text`, `effective_week int`, unique `(trade_id, revision)`.
- `survival_snapshots`: `season_id`, `week int not null`, `game_window text not null`, `snapshot_at timestamptz not null`, `projection_source text`, `model_version text not null`, `simulations int not null`, `input_hash text not null`, `results jsonb not null`, unique `(season_id, week, game_window, input_hash, model_version)`.
- `recaps`: `season_id`, `week int not null`, `recap_kind text not null`, `state_version int not null`, `prompt_version text not null`, `facts_hash text not null`, `body text not null`, `publication_state text not null default 'draft' check (publication_state in ('draft','sent','corrected'))`, unique `(season_id, week, recap_kind, state_version, prompt_version, facts_hash)`.

Add an index on every foreign key column. Enable RLS on all nine tables. Grant `select` only to `anon` and `authenticated`. Create one select policy per table named `Public <table> are readable` with `using (true)`. Seed season 2026:

```sql
insert into public.seasons (year, sleeper_league_id, phase, rules_version, expected_rosters)
values (2026, '1389372259260452864', 'preseason', '2026.1', 18)
on conflict (year) do update set sleeper_league_id = excluded.sleeper_league_id;
```

- [ ] **Step 4: Add database assertions**

```sql
-- supabase/tests/public_league_schema.sql
begin;
select plan(5);
select has_table('public', 'seasons');
select has_table('public', 'league_events');
select policies_are('public', 'seasons', array['Public seasons are readable']);
select col_is_pk('public', 'seasons', 'id');
select results_eq('select count(*)::int from public.seasons where year = 2026', array[1]);
select * from finish();
rollback;
```

- [ ] **Step 5: Verify and commit**

Run: `supabase db reset && supabase test db && pnpm test:agents`

Expected: 5 pgTAP assertions PASS; Python tests PASS.

```bash
git add supabase packages/league-automation/src/ultimate_guillotine/core packages/league-automation/tests/core
git commit -m "feat: add public league data model"
```

### Task 4: Private operational schema and automation role

**Files:**
- Create through CLI: `supabase/migrations/<generated>_private_automation_schema.sql`
- Create: `supabase/tests/private_automation_schema.sql`
- Create: `scripts/configure_worker_role.sql.example`

**Interfaces:**
- Consumes: public schema.
- Produces: `private` schema tables used by Tasks 6 through 11, and the `automation_worker` role.

- [ ] **Step 1: Create the migration**

Run: `supabase migration new private_automation_schema`

- [ ] **Step 2: Define the private schema**

Create schema `private` and revoke all from `public`, `anon`, and `authenticated`. Create these tables, each with `id bigint generated always as identity primary key` and `created_at timestamptz not null default now()`:

- `private.member_contacts`: `member_id bigint not null references public.members(id)`, `handle_hash text not null unique`, `alias text`.
- `private.delivery_targets`: `mode text not null unique check (mode in ('test','production'))`, `chat_guid text not null`, `chat_guid_hash text not null`, `participant_fingerprint text`, `label text not null`.
- `private.source_messages`: `source_guid text not null unique`, `chat_guid_hash text not null`, `sender_hash text`, `direction text not null check (direction in ('inbound','outbound'))`, `sent_at timestamptz not null`, `content_fingerprint text not null`, `excerpt text`, `trigger_name text`, unique `(chat_guid_hash, content_fingerprint, sent_at)`, index on `(chat_guid_hash, sent_at desc)`.
- `private.webhook_receipts`: `event_id text not null unique`, `received_at timestamptz not null default now()`, `outcome text not null`.
- `private.agent_runs`: `agent text not null`, `trigger text not null`, `idempotency_key text not null unique`, `input_version text`, `status text not null default 'running' check (status in ('running','succeeded','failed','duplicate'))`, `attempts int not null default 1`, `output_hash text`, `error text`, `invoked_by text`, `started_at timestamptz not null default now()`, `finished_at timestamptz`, index on `(agent, started_at desc)`.
- `private.outbound_messages`: `run_id bigint references private.agent_runs(id)`, `delivery_target_id bigint not null references private.delivery_targets(id)`, `content text not null`, `content_hash text not null`, `state text not null default 'reserved' check (state in ('reserved','sending','sent','reconciled','failed'))`, `reserved_at timestamptz not null default now()`, `sent_at timestamptz`, `bluebubbles_guid text`, `error text`, unique `(delivery_target_id, content_hash, reserved_at)`, index on `(delivery_target_id, state)`.
- `private.projection_snapshots`: `season_id bigint not null references public.seasons(id)`, `week int not null`, `source text not null`, `source_at timestamptz not null`, `coverage numeric(5,4) not null`, `payload jsonb not null`.
- `private.knowledge_sources`: `source_key text not null unique`, `version text not null`, `path text not null`, `sha256 text not null`.
- `private.heartbeats`: `component text not null unique`, `beat_at timestamptz not null default now()`.
- `private.expected_runs`: `job_name text not null unique`, `agent text not null`, `max_gap_minutes int not null`, `schedule text not null`.

Store no password or token in any table. Store exact chat GUIDs only in `private.delivery_targets`.

- [ ] **Step 3: Create the least-privilege role**

```sql
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'automation_worker') then
    create role automation_worker nologin;
  end if;
end $$;

grant usage on schema private to automation_worker;
grant select, insert, update on all tables in schema private to automation_worker;
grant usage, select on all sequences in schema private to automation_worker;
alter default privileges in schema private grant select, insert, update on tables to automation_worker;
alter default privileges in schema private grant usage, select on sequences to automation_worker;
grant select, insert, update on public.seasons, public.members, public.teams,
  public.weekly_results, public.league_events, public.trades,
  public.trade_revisions, public.survival_snapshots, public.recaps
  to automation_worker;
grant usage, select on all sequences in schema public to automation_worker;
```

No `delete` grant anywhere. No queue extension.

- [ ] **Step 4: Add the login example without a password**

```sql
-- scripts/configure_worker_role.sql.example
-- Run interactively against the hosted project with a freshly generated password.
-- Never commit the substituted value.
create role ultimate_guillotine_mac login password :'worker_password';
grant automation_worker to ultimate_guillotine_mac;
```

- [ ] **Step 5: Add database assertions**

```sql
-- supabase/tests/private_automation_schema.sql
begin;
select plan(6);
select has_schema('private');
select has_table('private', 'agent_runs');
select has_table('private', 'outbound_messages');
select has_table('private', 'webhook_receipts');
select has_role('automation_worker');
select is_empty($$select 1 from information_schema.role_table_grants where grantee = 'anon' and table_schema = 'private'$$);
select * from finish();
rollback;
```

- [ ] **Step 6: Verify and commit**

Run: `supabase db reset && supabase test db && supabase db advisors`

Expected: 11 pgTAP assertions PASS across both files; no unexplained security advisor finding.

```bash
git add supabase scripts/configure_worker_role.sql.example
git commit -m "feat: add private automation schema and worker role"
```

### Task 5: Database connection and repositories

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/data/__init__.py`
- Create: `packages/league-automation/src/ultimate_guillotine/data/database.py`
- Create: `packages/league-automation/src/ultimate_guillotine/data/repositories.py`
- Create: `packages/league-automation/tests/data/conftest.py`
- Create: `packages/league-automation/tests/data/test_repositories.py`

**Interfaces:**
- Consumes: `Settings.database_url`, private schema.
- Produces:
  - `connect(settings) -> psycopg.Connection` (autocommit off; callers commit).
  - `RunRepository(conn).reserve(agent: str, trigger: str, idempotency_key: str, invoked_by: str | None = None) -> int | None` returns the new run id or `None` when the key already exists.
  - `RunRepository.finish(run_id: int, status: str, output_hash: str | None = None, error: str | None = None) -> None`.
  - `RunRepository.last_started(agent: str) -> datetime | None`.
  - `TargetRepository(conn).get(mode: DeliveryMode) -> DeliveryTarget | None` and `.upsert(mode, chat_guid, participant_fingerprint, label) -> int`.
  - `OutboundRepository(conn).reserve(run_id, target_id, content, content_hash) -> int`, `.set_state(outbound_id, state, bluebubbles_guid=None, error=None) -> None`, `.pending_sending(target_id, content_hash) -> OutboundRecord | None`.
  - `ReceiptRepository(conn).record(event_id: str, outcome: str) -> bool` returns `False` when already recorded.
  - `SourceMessageRepository(conn).upsert(msg: SourceMessage) -> bool` and `.latest_sent_at(chat_guid_hash: str) -> datetime | None`.
  - `HeartbeatRepository(conn).beat(component: str) -> None` and `.stale(older_than: timedelta, now: datetime) -> list[str]`.
  - `ExpectedRunRepository(conn).replace_all(rows: list[ExpectedRun]) -> None` and `.all() -> list[ExpectedRun]`.
  - Dataclasses `DeliveryTarget(id, mode, chat_guid, participant_fingerprint, label)`, `OutboundRecord(id, state, reserved_at, content_hash, bluebubbles_guid)`, `SourceMessage(source_guid, chat_guid_hash, sender_hash, direction, sent_at, content_fingerprint, excerpt, trigger_name)`, `ExpectedRun(job_name, agent, max_gap_minutes, schedule)`.
  - `chat_guid_hash(chat_guid: str) -> str` = SHA-256 hex of the GUID.

- [ ] **Step 1: Write the database-backed tests**

```python
# packages/league-automation/tests/data/conftest.py
import os

import psycopg
import pytest


@pytest.fixture
def conn():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    with psycopg.connect(url) as connection:
        yield connection
        connection.rollback()
```

```python
# packages/league-automation/tests/data/test_repositories.py
from datetime import UTC, datetime, timedelta

from ultimate_guillotine.config import DeliveryMode
from ultimate_guillotine.data.repositories import (
    HeartbeatRepository,
    OutboundRepository,
    ReceiptRepository,
    RunRepository,
    TargetRepository,
)


def test_reserve_run_is_idempotent(conn) -> None:
    runs = RunRepository(conn)
    first = runs.reserve("self-test", "cli", "key-1")
    second = runs.reserve("self-test", "cli", "key-1")
    assert first is not None
    assert second is None


def test_receipt_records_once(conn) -> None:
    receipts = ReceiptRepository(conn)
    assert receipts.record("evt-1", "processed") is True
    assert receipts.record("evt-1", "processed") is False


def test_outbound_pending_sending_lookup(conn) -> None:
    targets = TargetRepository(conn)
    target_id = targets.upsert(DeliveryMode.TEST, "iMessage;+;chat-test", None, "self-test")
    outbound = OutboundRepository(conn)
    oid = outbound.reserve(None, target_id, "hello", "abc")
    assert outbound.pending_sending(target_id, "abc") is None
    outbound.set_state(oid, "sending")
    assert outbound.pending_sending(target_id, "abc").id == oid


def test_stale_heartbeats(conn) -> None:
    beats = HeartbeatRepository(conn)
    beats.beat("listener")
    now = datetime.now(UTC)
    assert beats.stale(timedelta(minutes=5), now) == []
    assert beats.stale(timedelta(seconds=-1), now) == ["listener"]
```

- [ ] **Step 2: Run the tests red**

Run: `TEST_DATABASE_URL=$(supabase status -o env | grep DB_URL | cut -d= -f2- | tr -d '"') uv run --project packages/league-automation pytest packages/league-automation/tests/data -v`

Expected: FAIL, `data.repositories` missing.

- [ ] **Step 3: Implement the connection helper**

```python
# packages/league-automation/src/ultimate_guillotine/data/database.py
import psycopg

from ultimate_guillotine.config import Settings


def connect(settings: Settings) -> psycopg.Connection:
    return psycopg.connect(settings.database_url.get_secret_value(), autocommit=False)
```

- [ ] **Step 4: Implement the repositories**

Each repository class takes a `psycopg.Connection` and uses parameterized SQL only. Key statements:

- `RunRepository.reserve`: `insert into private.agent_runs (agent, trigger, idempotency_key, invoked_by) values (%s,%s,%s,%s) on conflict (idempotency_key) do nothing returning id`. Return `None` if no row.
- `RunRepository.finish`: update `status`, `output_hash`, `error`, `finished_at = now()` where `id = %s`.
- `RunRepository.last_started`: `select max(started_at) from private.agent_runs where agent = %s`.
- `TargetRepository.get`: `select id, mode, chat_guid, participant_fingerprint, label from private.delivery_targets where mode = %s`.
- `TargetRepository.upsert`: insert with `chat_guid_hash = chat_guid_hash(chat_guid)` and `on conflict (mode) do update set chat_guid = excluded.chat_guid, chat_guid_hash = excluded.chat_guid_hash, participant_fingerprint = excluded.participant_fingerprint, label = excluded.label returning id`.
- `OutboundRepository.pending_sending`: `select id, state, reserved_at, content_hash, bluebubbles_guid from private.outbound_messages where delivery_target_id = %s and content_hash = %s and state = 'sending' order by reserved_at desc limit 1`.
- `ReceiptRepository.record`: `insert ... on conflict (event_id) do nothing returning id`; `True` when a row is returned.
- `SourceMessageRepository.upsert`: `insert ... on conflict (source_guid) do nothing returning id`.
- `HeartbeatRepository.beat`: `insert into private.heartbeats (component, beat_at) values (%s, now()) on conflict (component) do update set beat_at = now()`.
- `HeartbeatRepository.stale`: `select component from private.heartbeats where beat_at < %s` with `now - older_than`.
- `ExpectedRunRepository.replace_all`: delete all rows then insert each. Grant note: `automation_worker` has no delete, so `replace_all` is executed by the developer login during install, never by a cron job. Document this in the docstring.

- [ ] **Step 5: Run green and commit**

Run: `TEST_DATABASE_URL=... uv run --project packages/league-automation pytest packages/league-automation/tests/data -v && pnpm lint:agents`

Expected: 4 tests PASS.

```bash
git add packages/league-automation/src/ultimate_guillotine/data packages/league-automation/tests/data
git commit -m "feat: add Postgres repositories for automation state"
```

### Task 6: Sleeper client and seasonal synchronization

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/sleeper/__init__.py`
- Create: `packages/league-automation/src/ultimate_guillotine/sleeper/client.py`
- Create: `packages/league-automation/src/ultimate_guillotine/sleeper/models.py`
- Create: `packages/league-automation/src/ultimate_guillotine/sleeper/sync.py`
- Create: `packages/league-automation/tests/sleeper/test_client.py`
- Create: `packages/league-automation/tests/sleeper/test_sync.py`
- Create: `packages/league-automation/tests/fixtures/sleeper/league_2026.json`
- Create: `packages/league-automation/tests/fixtures/sleeper/users_2026.json`
- Create: `packages/league-automation/tests/fixtures/sleeper/rosters_2026.json`

**Interfaces:**
- Consumes: `Settings.sleeper_league_id`.
- Produces: `SleeperClient(http: httpx.Client)` with `get_league(league_id) -> SleeperLeague`, `get_users(league_id) -> list[SleeperUser]`, `get_rosters(league_id) -> list[SleeperRoster]`, `get_matchups(league_id, week) -> list[dict]`, `get_nfl_state() -> dict`; `sync_season(client, conn, year: int, league_id: str) -> SyncReport(members: int, teams: int)`.

- [ ] **Step 1: Save fixtures and write failing tests**

Fixtures are hand-written, anonymized JSON in the shape of the Sleeper API: `league_2026.json` with `season: "2026"`, `total_rosters: 18`, `name: "Ultimate Guillotine League"`; `users_2026.json` with 18 entries of `user_id` and `display_name` like `Member01`; `rosters_2026.json` with 18 entries of `roster_id` and `owner_id`.

```python
# packages/league-automation/tests/sleeper/test_client.py
import json
from pathlib import Path

import httpx
import respx

from ultimate_guillotine.sleeper.client import SleeperClient

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sleeper"


@respx.mock
def test_get_league_parses_roster_count() -> None:
    respx.get("https://api.sleeper.app/v1/league/1389372259260452864").mock(
        return_value=httpx.Response(200, json=json.loads((FIXTURES / "league_2026.json").read_text()))
    )
    client = SleeperClient(httpx.Client())
    league = client.get_league("1389372259260452864")
    assert league.season == "2026"
    assert league.total_rosters == 18
```

```python
# packages/league-automation/tests/sleeper/test_sync.py
import pytest

from ultimate_guillotine.sleeper.models import SleeperLeague
from ultimate_guillotine.sleeper.sync import validate_league


def test_validate_rejects_wrong_roster_count() -> None:
    league = SleeperLeague(league_id="1389372259260452864", name="Ultimate Guillotine League", season="2026", total_rosters=12)
    with pytest.raises(ValueError, match="expected 18 rosters"):
        validate_league(league, expected_id="1389372259260452864", expected_rosters=18)


def test_validate_rejects_wrong_id() -> None:
    league = SleeperLeague(league_id="1", name="Ultimate Guillotine League", season="2026", total_rosters=18)
    with pytest.raises(ValueError, match="league id"):
        validate_league(league, expected_id="1389372259260452864", expected_rosters=18)
```

- [ ] **Step 2: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/sleeper -v`

Expected: FAIL, modules absent.

- [ ] **Step 3: Implement models and client**

`SleeperLeague(league_id, name, season, total_rosters)`, `SleeperUser(user_id, display_name)`, `SleeperRoster(roster_id, owner_id)` as frozen Pydantic models with `extra="ignore"`. `SleeperClient` uses `base_url="https://api.sleeper.app/v1"` and `timeout=10.0` on the provided `httpx.Client`, calls `raise_for_status()`, and parses with `model_validate`. No write methods.

- [ ] **Step 4: Implement validation and sync**

`validate_league` raises `ValueError("league id mismatch")` or `ValueError("expected 18 rosters, got N")`. `sync_season` validates, then inside one transaction: upsert `public.members` by `display_name`, look up `seasons.id` for `year`, upsert `public.teams` by `(season_id, sleeper_roster_id)` with `team_name` defaulting to the display name, and returns `SyncReport`. It never writes elimination state.

- [ ] **Step 5: Verify and commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation/src/ultimate_guillotine/sleeper packages/league-automation/tests/sleeper packages/league-automation/tests/fixtures
git commit -m "feat: synchronize 2026 Sleeper league"
```

### Task 7: BlueBubbles client and participant fingerprint

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/messages/__init__.py`
- Create: `packages/league-automation/src/ultimate_guillotine/messages/bluebubbles.py`
- Create: `packages/league-automation/src/ultimate_guillotine/messages/fingerprint.py`
- Create: `packages/league-automation/tests/messages/test_bluebubbles.py`
- Create: `packages/league-automation/tests/messages/test_fingerprint.py`
- Create: `packages/league-automation/tests/fixtures/bluebubbles/new_message.json`

**Interfaces:**
- Consumes: `Settings.bluebubbles_server_url`, `Settings.bluebubbles_password`.
- Produces:
  - `InboundMessage(guid, chat_guid, sender_address, text, is_from_me, is_group, sent_at)` frozen model.
  - `parse_webhook(payload: dict) -> InboundMessage | None` (returns `None` for non `new-message` types or missing chat GUID).
  - `BlueBubblesClient(server_url, password, http: httpx.Client)` with `ping() -> bool`, `server_info() -> dict`, `chat_participants(chat_guid) -> list[str]`, `messages_after(chat_guid, after: datetime, limit=100) -> list[InboundMessage]`, `send_text(chat_guid, text) -> str`, `ensure_webhook(url: str) -> None`.
  - `participant_fingerprint(addresses: list[str]) -> str`.
  - `class BlueBubblesError(Exception)`.

- [ ] **Step 1: Write the failing tests**

Fixture `new_message.json`:

```json
{"type": "new-message", "data": {"guid": "p:0/ABC", "text": "🚨 Max sends Chase to Evan", "isFromMe": false, "isGroup": true, "dateCreated": 1788870000000, "handle": {"address": "+15555550100"}, "chats": [{"guid": "iMessage;+;chat-test"}]}}
```

```python
# packages/league-automation/tests/messages/test_bluebubbles.py
import json
from datetime import UTC
from pathlib import Path

import httpx
import pytest
import respx

from ultimate_guillotine.messages.bluebubbles import BlueBubblesClient, BlueBubblesError, parse_webhook

FIXTURE = Path(__file__).parent.parent / "fixtures" / "bluebubbles" / "new_message.json"


def test_parse_webhook_new_message() -> None:
    msg = parse_webhook(json.loads(FIXTURE.read_text()))
    assert msg.chat_guid == "iMessage;+;chat-test"
    assert msg.sender_address == "+15555550100"
    assert msg.is_group is True
    assert msg.sent_at.tzinfo is UTC


def test_parse_webhook_ignores_other_events() -> None:
    assert parse_webhook({"type": "typing-indicator", "data": {}}) is None


@respx.mock
def test_send_text_posts_chat_guid_and_returns_guid() -> None:
    route = respx.post("http://bb.local/api/v1/message/text").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": {"guid": "sent-1"}})
    )
    client = BlueBubblesClient("http://bb.local", "pw", httpx.Client())
    assert client.send_text("iMessage;+;chat-test", "hi") == "sent-1"
    body = json.loads(route.calls.last.request.content)
    assert body["chatGuid"] == "iMessage;+;chat-test"
    assert body["message"] == "hi"
    assert "tempGuid" in body
    assert "method" not in body
    assert route.calls.last.request.url.params["password"] == "pw"


@respx.mock
def test_send_text_raises_on_error() -> None:
    respx.post("http://bb.local/api/v1/message/text").mock(return_value=httpx.Response(500, json={"status": 500, "message": "boom"}))
    client = BlueBubblesClient("http://bb.local", "pw", httpx.Client())
    with pytest.raises(BlueBubblesError):
        client.send_text("iMessage;+;chat-test", "hi")


@respx.mock
def test_messages_after_uses_ms_and_parses() -> None:
    route = respx.get("http://bb.local/api/v1/chat/iMessage%3B%2B%3Bchat-test/message").mock(
        return_value=httpx.Response(200, json={"status": 200, "data": [json.loads(FIXTURE.read_text())["data"]]})
    )
    client = BlueBubblesClient("http://bb.local", "pw", httpx.Client())
    from datetime import datetime
    out = client.messages_after("iMessage;+;chat-test", datetime(2026, 9, 8, tzinfo=UTC))
    assert route.calls.last.request.url.params["after"] == "1788825600000"
    assert route.calls.last.request.url.params["sort"] == "ASC"
    assert out[0].guid == "p:0/ABC"


@respx.mock
def test_ensure_webhook_creates_when_missing() -> None:
    respx.get("http://bb.local/api/v1/webhook").mock(return_value=httpx.Response(200, json={"status": 200, "data": []}))
    create = respx.post("http://bb.local/api/v1/webhook").mock(return_value=httpx.Response(200, json={"status": 200, "data": {"id": 1}}))
    BlueBubblesClient("http://bb.local", "pw", httpx.Client()).ensure_webhook("http://127.0.0.1:8646/bluebubbles-webhook?password=x")
    assert json.loads(create.calls.last.request.content)["events"] == ["new-message"]
```

```python
# packages/league-automation/tests/messages/test_fingerprint.py
from ultimate_guillotine.messages.fingerprint import participant_fingerprint


def test_fingerprint_is_order_and_format_insensitive() -> None:
    a = participant_fingerprint(["+1 (555) 555-0100", "ben@example.com"])
    b = participant_fingerprint(["BEN@example.com", "+15555550100"])
    assert a == b
    assert len(a) == 32


def test_fingerprint_changes_with_membership() -> None:
    assert participant_fingerprint(["+15555550100"]) != participant_fingerprint(["+15555550100", "+15555550101"])
```

- [ ] **Step 2: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/messages -v`

Expected: FAIL, modules absent.

- [ ] **Step 3: Implement the fingerprint**

```python
# packages/league-automation/src/ultimate_guillotine/messages/fingerprint.py
import hashlib
import re


def normalize_address(address: str) -> str:
    value = address.strip().lower()
    if "@" in value:
        return value
    digits = re.sub(r"\D", "", value)
    return f"+{digits}" if digits else value


def participant_fingerprint(addresses: list[str]) -> str:
    normalized = sorted({normalize_address(a) for a in addresses if a and a.strip()})
    return hashlib.sha256("\n".join(normalized).encode()).hexdigest()[:32]
```

- [ ] **Step 4: Implement the client**

```python
# packages/league-automation/src/ultimate_guillotine/messages/bluebubbles.py
import uuid
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
from pydantic import BaseModel


class BlueBubblesError(Exception):
    pass


class InboundMessage(BaseModel, frozen=True):
    guid: str
    chat_guid: str
    sender_address: str | None
    text: str
    is_from_me: bool
    is_group: bool
    sent_at: datetime


def _record_to_message(record: dict) -> InboundMessage | None:
    chats = record.get("chats") or []
    chat_guid = record.get("chatGuid") or (chats[0].get("guid") if chats else None)
    if not chat_guid or not record.get("guid"):
        return None
    handle = record.get("handle") or {}
    created = record.get("dateCreated") or 0
    return InboundMessage(
        guid=record["guid"],
        chat_guid=chat_guid,
        sender_address=handle.get("address"),
        text=record.get("text") or "",
        is_from_me=bool(record.get("isFromMe")),
        is_group=bool(record.get("isGroup")) or ";+;" in chat_guid,
        sent_at=datetime.fromtimestamp(created / 1000, tz=UTC),
    )


def parse_webhook(payload: dict) -> InboundMessage | None:
    if payload.get("type") != "new-message":
        return None
    return _record_to_message(payload.get("data") or {})


class BlueBubblesClient:
    def __init__(self, server_url: str, password: str, http: httpx.Client) -> None:
        self._base = server_url.rstrip("/")
        self._password = password
        self._http = http

    def _request(self, method: str, path: str, **kwargs) -> dict:
        params = dict(kwargs.pop("params", {}) or {})
        params["password"] = self._password
        try:
            response = self._http.request(method, f"{self._base}{path}", params=params, timeout=15.0, **kwargs)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BlueBubblesError(f"{method} {path} failed: {exc.__class__.__name__}") from exc
        return response.json()

    def ping(self) -> bool:
        try:
            return self._request("GET", "/api/v1/ping").get("data") == "pong"
        except BlueBubblesError:
            return False

    def server_info(self) -> dict:
        return self._request("GET", "/api/v1/server/info").get("data") or {}

    def chat_participants(self, chat_guid: str) -> list[str]:
        data = self._request("GET", f"/api/v1/chat/{quote(chat_guid, safe='')}", params={"with": "participants"}).get("data") or {}
        return [p.get("address") for p in data.get("participants") or [] if p.get("address")]

    def messages_after(self, chat_guid: str, after: datetime, limit: int = 100) -> list[InboundMessage]:
        params = {"after": str(int(after.timestamp() * 1000)), "sort": "ASC", "limit": str(limit), "with": "handle"}
        data = self._request("GET", f"/api/v1/chat/{quote(chat_guid, safe='')}/message", params=params).get("data") or []
        return [m for m in (_record_to_message(r) for r in data) if m]

    def send_text(self, chat_guid: str, text: str) -> str:
        body = {"chatGuid": chat_guid, "tempGuid": uuid.uuid4().hex, "message": text}
        data = self._request("POST", "/api/v1/message/text", json=body).get("data") or {}
        guid = data.get("guid")
        if not guid:
            raise BlueBubblesError("send returned no message guid")
        return guid

    def ensure_webhook(self, url: str) -> None:
        existing = self._request("GET", "/api/v1/webhook").get("data") or []
        if any(w.get("url") == url for w in existing):
            return
        self._request("POST", "/api/v1/webhook", json={"url": url, "events": ["new-message"]})
```

Error messages never include the request URL with the password or the message body.

- [ ] **Step 5: Run green and commit**

Run: `pnpm test:agents && pnpm lint:agents`

Expected: 8 new tests PASS.

```bash
git add packages/league-automation/src/ultimate_guillotine/messages packages/league-automation/tests/messages packages/league-automation/tests/fixtures/bluebubbles
git commit -m "feat: add BlueBubbles client and participant fingerprint"
```

### Task 8: Discord notifier

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/ops/__init__.py`
- Create: `packages/league-automation/src/ultimate_guillotine/ops/notify.py`
- Create: `packages/league-automation/tests/ops/test_notify.py`

**Interfaces:**
- Consumes: `Settings.hermes_profile_home`, channel names from `Settings`.
- Produces: `HermesNotifier(profile_home: str, runner=subprocess.run)` with `send(channel: str, text: str) -> bool`, and convenience `ops(text)`, `feed(text)`, `drafts(text)`, `alerts(text)` created by `HermesNotifier.from_settings(settings)`. Never raises.

- [ ] **Step 1: Write the failing tests**

```python
# packages/league-automation/tests/ops/test_notify.py
import subprocess

from ultimate_guillotine.ops.notify import HermesNotifier


class FakeRunner:
    def __init__(self, returncode: int = 0) -> None:
        self.calls = []
        self.returncode = returncode

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, self.returncode, "", "")


def test_send_invokes_hermes_send_with_profile_home() -> None:
    runner = FakeRunner()
    notifier = HermesNotifier("/tmp/profile", runner=runner)
    assert notifier.send("#guillotine-ops", "run ok") is True
    args, kwargs = runner.calls[0]
    assert args[:4] == ["hermes", "send", "--to", "discord:#guillotine-ops"]
    assert args[-1] == "run ok"
    assert kwargs["env"]["HERMES_HOME"] == "/tmp/profile"


def test_send_returns_false_on_failure_and_never_raises() -> None:
    notifier = HermesNotifier("/tmp/profile", runner=FakeRunner(returncode=1))
    assert notifier.send("#guillotine-ops", "x") is False
```

- [ ] **Step 2: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/ops -v`

Expected: FAIL, module absent.

- [ ] **Step 3: Implement**

```python
# packages/league-automation/src/ultimate_guillotine/ops/notify.py
import logging
import os
import subprocess
from pathlib import Path

from ultimate_guillotine.config import Settings

log = logging.getLogger(__name__)


class HermesNotifier:
    def __init__(self, profile_home: str, runner=subprocess.run, channels: dict[str, str] | None = None) -> None:
        self._home = str(Path(profile_home).expanduser())
        self._runner = runner
        self._channels = channels or {}

    @classmethod
    def from_settings(cls, settings: Settings, runner=subprocess.run) -> "HermesNotifier":
        return cls(settings.hermes_profile_home, runner, {
            "ops": settings.discord_ops_channel,
            "feed": settings.discord_feed_channel,
            "drafts": settings.discord_drafts_channel,
            "alerts": settings.discord_alerts_channel,
        })

    def send(self, channel: str, text: str) -> bool:
        env = {**os.environ, "HERMES_HOME": self._home}
        try:
            result = self._runner(["hermes", "send", "--to", f"discord:{channel}", "--quiet", text], env=env, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                log.warning("hermes send to %s failed with code %s", channel, result.returncode)
                return False
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("hermes send to %s raised %s", channel, exc.__class__.__name__)
            return False

    def ops(self, text: str) -> bool:
        return self.send(self._channels["ops"], text)

    def feed(self, text: str) -> bool:
        return self.send(self._channels["feed"], text)

    def drafts(self, text: str) -> bool:
        return self.send(self._channels["drafts"], text)

    def alerts(self, text: str) -> bool:
        return self.send(self._channels["alerts"], text)
```

- [ ] **Step 4: Run green and commit**

Run: `pnpm test:agents && pnpm lint:agents`

```bash
git add packages/league-automation/src/ultimate_guillotine/ops packages/league-automation/tests/ops
git commit -m "feat: add Discord notifier via hermes send"
```

### Task 9: Delivery layer with effectively-once semantics

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/messages/delivery.py`
- Create: `packages/league-automation/tests/messages/test_delivery.py`

**Interfaces:**
- Consumes: `BlueBubblesClient`, `TargetRepository`, `OutboundRepository`, `HermesNotifier`, `sign()`, `participant_fingerprint()`.
- Produces:
  - `class TargetMismatch(Exception)`, `class DeliveryDisabled(Exception)`.
  - `DeliveryResult(status: Literal["sent","reconciled"], outbound_id: int, message_guid: str | None)`.
  - `DeliveryService(settings, client, targets, outbound, notifier, clock=lambda: datetime.now(UTC), crash_after_send=False)` with `deliver(run_id: int | None, agent: str, content: str) -> DeliveryResult`.
  - `content_hash(text: str) -> str` (SHA-256 hex of the signed text).

- [ ] **Step 1: Write the failing tests with in-memory fakes**

```python
# packages/league-automation/tests/messages/test_delivery.py
from datetime import UTC, datetime

import pytest

from ultimate_guillotine.config import DeliveryMode, Settings
from ultimate_guillotine.core.signature import sign
from ultimate_guillotine.data.repositories import DeliveryTarget, OutboundRecord
from ultimate_guillotine.messages.bluebubbles import InboundMessage
from ultimate_guillotine.messages.delivery import DeliveryDisabled, DeliveryService, TargetMismatch, content_hash
from ultimate_guillotine.messages.fingerprint import participant_fingerprint

TEST_GUID = "iMessage;+;chat-test"
PROD_GUID = "iMessage;+;chat-prod"
PROD_MEMBERS = ["+15555550100", "+15555550101"]


class FakeClient:
    def __init__(self) -> None:
        self.sent = []
        self.participants = {PROD_GUID: PROD_MEMBERS, TEST_GUID: ["+15555550100"]}
        self.history = []

    def chat_participants(self, chat_guid):
        return self.participants[chat_guid]

    def send_text(self, chat_guid, text):
        self.sent.append((chat_guid, text))
        return f"guid-{len(self.sent)}"

    def messages_after(self, chat_guid, after, limit=100):
        return self.history


class FakeTargets:
    def __init__(self, rows):
        self.rows = rows

    def get(self, mode):
        return self.rows.get(mode)


class FakeOutbound:
    def __init__(self) -> None:
        self.records = {}
        self.pending = None

    def reserve(self, run_id, target_id, content, hash_):
        oid = len(self.records) + 1
        self.records[oid] = {"state": "reserved", "hash": hash_}
        return oid

    def set_state(self, oid, state, bluebubbles_guid=None, error=None):
        self.records[oid]["state"] = state
        self.records[oid]["guid"] = bluebubbles_guid

    def pending_sending(self, target_id, hash_):
        return self.pending


class FakeNotifier:
    def __init__(self) -> None:
        self.feed_posts = []

    def feed(self, text):
        self.feed_posts.append(text)
        return True


def make(mode: DeliveryMode, client=None, outbound=None, **kw):
    settings = Settings(
        database_url="postgresql://x:y@example.invalid/db",
        delivery_mode=mode,
        test_chat_guid=TEST_GUID,
        production_chat_guid=PROD_GUID,
        production_participant_fingerprint=participant_fingerprint(PROD_MEMBERS),
    )
    targets = FakeTargets({
        DeliveryMode.TEST: DeliveryTarget(1, "test", TEST_GUID, None, "self-test"),
        DeliveryMode.PRODUCTION: DeliveryTarget(2, "production", PROD_GUID, participant_fingerprint(PROD_MEMBERS), "league"),
    })
    client = client or FakeClient()
    outbound = outbound or FakeOutbound()
    notifier = FakeNotifier()
    return DeliveryService(settings, client, targets, outbound, notifier, **kw), client, outbound, notifier


def test_test_mode_sends_signed_to_test_chat_only() -> None:
    service, client, outbound, notifier = make(DeliveryMode.TEST)
    result = service.deliver(None, "self-test", "hello")
    assert result.status == "sent"
    assert client.sent == [(TEST_GUID, sign("hello"))]
    assert outbound.records[1]["state"] == "sent"
    assert len(notifier.feed_posts) == 1


def test_disabled_mode_sends_nothing() -> None:
    service, client, _, _ = make(DeliveryMode.DISABLED)
    with pytest.raises(DeliveryDisabled):
        service.deliver(None, "self-test", "hello")
    assert client.sent == []


def test_production_rejects_participant_change() -> None:
    client = FakeClient()
    client.participants[PROD_GUID] = PROD_MEMBERS + ["+15555550199"]
    service, client, outbound, _ = make(DeliveryMode.PRODUCTION, client=client)
    with pytest.raises(TargetMismatch):
        service.deliver(None, "self-test", "hello")
    assert client.sent == []
    assert outbound.records == {}


def test_crash_after_send_then_retry_reconciles() -> None:
    service, client, outbound, notifier = make(DeliveryMode.TEST, crash_after_send=True)
    with pytest.raises(RuntimeError):
        service.deliver(None, "self-test", "hello")
    assert outbound.records[1]["state"] == "sending"
    outbound.pending = OutboundRecord(1, "sending", datetime.now(UTC), content_hash("hello"), None)
    client.history = [InboundMessage(guid="g1", chat_guid=TEST_GUID, sender_address=None, text=sign("hello"), is_from_me=True, is_group=True, sent_at=datetime.now(UTC))]
    retry, _, _, _ = make(DeliveryMode.TEST, client=client, outbound=outbound)
    result = retry.deliver(None, "self-test", "hello")
    assert result.status == "reconciled"
    assert len(client.sent) == 1
    assert outbound.records[1]["state"] == "reconciled"
```

- [ ] **Step 2: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/messages/test_delivery.py -v`

Expected: FAIL, `delivery` missing.

- [ ] **Step 3: Implement**

```python
# packages/league-automation/src/ultimate_guillotine/messages/delivery.py
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from ultimate_guillotine.config import DeliveryMode, Settings
from ultimate_guillotine.core.signature import sign
from ultimate_guillotine.messages.fingerprint import participant_fingerprint


class TargetMismatch(Exception):
    pass


class DeliveryDisabled(Exception):
    pass


@dataclass(frozen=True)
class DeliveryResult:
    status: Literal["sent", "reconciled"]
    outbound_id: int
    message_guid: str | None


def content_hash(text: str) -> str:
    return hashlib.sha256(sign(text).encode()).hexdigest()


class DeliveryService:
    def __init__(self, settings: Settings, client, targets, outbound, notifier, clock=lambda: datetime.now(UTC), crash_after_send: bool = False) -> None:
        self._settings = settings
        self._client = client
        self._targets = targets
        self._outbound = outbound
        self._notifier = notifier
        self._clock = clock
        self._crash_after_send = crash_after_send

    def _resolve_target(self):
        mode = self._settings.delivery_mode
        if mode is DeliveryMode.DISABLED:
            raise DeliveryDisabled("delivery mode is disabled")
        target = self._targets.get(mode)
        if target is None:
            raise TargetMismatch(f"no delivery target configured for {mode}")
        expected_guid = self._settings.test_chat_guid if mode is DeliveryMode.TEST else self._settings.production_chat_guid
        if target.chat_guid != expected_guid:
            raise TargetMismatch("stored target does not match configured chat")
        if mode is DeliveryMode.PRODUCTION:
            observed = participant_fingerprint(self._client.chat_participants(target.chat_guid))
            if observed != self._settings.production_participant_fingerprint or observed != target.participant_fingerprint:
                raise TargetMismatch("participant fingerprint changed")
        return target

    def deliver(self, run_id: int | None, agent: str, content: str) -> DeliveryResult:
        target = self._resolve_target()
        signed = sign(content)
        digest = content_hash(content)
        pending = self._outbound.pending_sending(target.id, digest)
        if pending is not None:
            since = pending.reserved_at - timedelta(minutes=1)
            for msg in self._client.messages_after(target.chat_guid, since):
                if msg.is_from_me and msg.text.strip() == signed.strip():
                    self._outbound.set_state(pending.id, "reconciled", bluebubbles_guid=msg.guid)
                    return DeliveryResult("reconciled", pending.id, msg.guid)
            self._outbound.set_state(pending.id, "failed", error="unreconciled send; retrying")
        outbound_id = self._outbound.reserve(run_id, target.id, signed, digest)
        self._outbound.set_state(outbound_id, "sending")
        guid = self._client.send_text(target.chat_guid, signed)
        if self._crash_after_send:
            raise RuntimeError("simulated crash after send")
        self._outbound.set_state(outbound_id, "sent", bluebubbles_guid=guid)
        self._notifier.feed(f"[{agent}] [{self._settings.delivery_mode}] outbound #{outbound_id}\n{signed}")
        return DeliveryResult("sent", outbound_id, guid)
```

- [ ] **Step 4: Run green and commit**

Run: `pnpm test:agents && pnpm lint:agents`

Expected: 4 delivery tests PASS.

```bash
git add packages/league-automation/src/ultimate_guillotine/messages/delivery.py packages/league-automation/tests/messages/test_delivery.py
git commit -m "feat: add effectively-once iMessage delivery layer"
```

### Task 10: Inbound processor and webhook listener

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/listener/__init__.py`
- Create: `packages/league-automation/src/ultimate_guillotine/listener/processing.py`
- Create: `packages/league-automation/src/ultimate_guillotine/listener/app.py`
- Create: `packages/league-automation/tests/listener/test_processing.py`
- Create: `packages/league-automation/tests/listener/test_app.py`
- Create: `services/webhook-listener/main.py`

**Interfaces:**
- Consumes: `parse_webhook`, `InboundMessage`, `ReceiptRepository`, `SourceMessageRepository`, `TargetRepository`, `HeartbeatRepository`, `DeliveryService`, `is_signed`.
- Produces:
  - `Trigger(name: str, matches: Callable[[InboundMessage], bool], handle: Callable[[InboundMessage], None])`.
  - `TriggerRegistry()` with `register(trigger)` and `match(msg) -> list[Trigger]`.
  - `InboundProcessor(allowed_chat_guids: set[str], registry, receipts, sources, on_error=None)` with `process(msg: InboundMessage, event_id: str) -> str` returning one of `duplicate`, `ignored_chat`, `ignored_bot`, `no_trigger`, `handled:<names>`.
  - `create_app(processor, heartbeats, webhook_password: str) -> fastapi.FastAPI` exposing `POST /bluebubbles-webhook` and `GET /healthz`.
  - `ping_trigger(delivery: DeliveryService, test_chat_guid: str) -> Trigger` which replies `pong <utc time>` when a message in the test chat is exactly `bot: ping`.

- [ ] **Step 1: Write the failing processor tests**

```python
# packages/league-automation/tests/listener/test_processing.py
from datetime import UTC, datetime

from ultimate_guillotine.core.signature import sign
from ultimate_guillotine.listener.processing import InboundProcessor, Trigger, TriggerRegistry
from ultimate_guillotine.messages.bluebubbles import InboundMessage

CHAT = "iMessage;+;chat-test"


def msg(text, chat=CHAT, from_me=False, guid="g1"):
    return InboundMessage(guid=guid, chat_guid=chat, sender_address="+15555550100", text=text, is_from_me=from_me, is_group=True, sent_at=datetime.now(UTC))


class FakeReceipts:
    def __init__(self):
        self.seen = set()

    def record(self, event_id, outcome):
        if event_id in self.seen:
            return False
        self.seen.add(event_id)
        return True


class FakeSources:
    def __init__(self):
        self.rows = []

    def upsert(self, row):
        self.rows.append(row)
        return True


def build(trigger=None):
    registry = TriggerRegistry()
    if trigger:
        registry.register(trigger)
    return InboundProcessor({CHAT}, registry, FakeReceipts(), FakeSources())


def test_duplicate_event_is_dropped() -> None:
    processor = build()
    assert processor.process(msg("hi"), "evt") == "no_trigger"
    assert processor.process(msg("hi"), "evt") == "duplicate"


def test_unlisted_chat_is_ignored() -> None:
    assert build().process(msg("hi", chat="iMessage;+;other"), "e") == "ignored_chat"


def test_signed_bot_message_is_ignored() -> None:
    assert build().process(msg(sign("hello"), from_me=True), "e") == "ignored_bot"


def test_matching_trigger_runs_and_persists_source() -> None:
    calls = []
    trigger = Trigger("ping", lambda m: m.text == "bot: ping", lambda m: calls.append(m.guid))
    registry = TriggerRegistry()
    registry.register(trigger)
    sources = FakeSources()
    processor = InboundProcessor({CHAT}, registry, FakeReceipts(), sources)
    assert processor.process(msg("bot: ping"), "e") == "handled:ping"
    assert calls == ["g1"]
    assert sources.rows[0].trigger_name == "ping"
    assert sources.rows[0].excerpt == "bot: ping"


def test_handler_error_is_reported_not_raised() -> None:
    errors = []

    def boom(m):
        raise RuntimeError("x")

    registry = TriggerRegistry()
    registry.register(Trigger("boom", lambda m: True, boom))
    processor = InboundProcessor({CHAT}, registry, FakeReceipts(), FakeSources(), on_error=lambda name, exc: errors.append(name))
    assert processor.process(msg("hi"), "e") == "handled:boom"
    assert errors == ["boom"]
```

- [ ] **Step 2: Write the failing app tests**

```python
# packages/league-automation/tests/listener/test_app.py
import json
from pathlib import Path

from fastapi.testclient import TestClient

from ultimate_guillotine.listener.app import create_app

FIXTURE = Path(__file__).parent.parent / "fixtures" / "bluebubbles" / "new_message.json"


class FakeProcessor:
    def __init__(self):
        self.calls = []

    def process(self, msg, event_id):
        self.calls.append((msg.guid, event_id))
        return "no_trigger"


class FakeHeartbeats:
    def __init__(self):
        self.beats = 0

    def beat(self, component):
        self.beats += 1


def test_rejects_wrong_password() -> None:
    client = TestClient(create_app(FakeProcessor(), FakeHeartbeats(), "secret"))
    assert client.post("/bluebubbles-webhook?password=nope", json=json.loads(FIXTURE.read_text())).status_code == 401


def test_processes_new_message_and_beats() -> None:
    processor, beats = FakeProcessor(), FakeHeartbeats()
    client = TestClient(create_app(processor, beats, "secret"))
    response = client.post("/bluebubbles-webhook?password=secret", json=json.loads(FIXTURE.read_text()))
    assert response.status_code == 200
    assert response.json() == {"outcome": "no_trigger"}
    assert processor.calls == [("p:0/ABC", "p:0/ABC")]
    assert beats.beats == 1


def test_non_message_events_are_acknowledged() -> None:
    processor = FakeProcessor()
    client = TestClient(create_app(processor, FakeHeartbeats(), "secret"))
    assert client.post("/bluebubbles-webhook?password=secret", json={"type": "hello-world", "data": {}}).json() == {"outcome": "ignored_event"}
    assert processor.calls == []
```

- [ ] **Step 3: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/listener -v`

Expected: FAIL, modules absent.

- [ ] **Step 4: Implement processing**

```python
# packages/league-automation/src/ultimate_guillotine/listener/processing.py
import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from ultimate_guillotine.core.signature import is_signed
from ultimate_guillotine.data.repositories import SourceMessage, chat_guid_hash
from ultimate_guillotine.messages.bluebubbles import InboundMessage

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Trigger:
    name: str
    matches: Callable[[InboundMessage], bool]
    handle: Callable[[InboundMessage], None]


class TriggerRegistry:
    def __init__(self) -> None:
        self._triggers: list[Trigger] = []

    def register(self, trigger: Trigger) -> None:
        self._triggers.append(trigger)

    def match(self, msg: InboundMessage) -> list[Trigger]:
        return [t for t in self._triggers if t.matches(msg)]


def _fingerprint(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).lower().encode()).hexdigest()


def _sender_hash(address: str | None) -> str | None:
    return hashlib.sha256(address.encode()).hexdigest() if address else None


class InboundProcessor:
    def __init__(self, allowed_chat_guids: set[str], registry: TriggerRegistry, receipts, sources, on_error=None) -> None:
        self._allowed = allowed_chat_guids
        self._registry = registry
        self._receipts = receipts
        self._sources = sources
        self._on_error = on_error or (lambda name, exc: log.error("trigger %s failed: %s", name, exc.__class__.__name__))

    def process(self, msg: InboundMessage, event_id: str) -> str:
        if not self._receipts.record(event_id, "received"):
            return "duplicate"
        if msg.chat_guid not in self._allowed:
            return "ignored_chat"
        if msg.is_from_me and is_signed(msg.text):
            return "ignored_bot"
        triggers = self._registry.match(msg)
        if not triggers:
            return "no_trigger"
        names = ",".join(t.name for t in triggers)
        self._sources.upsert(SourceMessage(
            source_guid=msg.guid,
            chat_guid_hash=chat_guid_hash(msg.chat_guid),
            sender_hash=_sender_hash(msg.sender_address),
            direction="outbound" if msg.is_from_me else "inbound",
            sent_at=msg.sent_at,
            content_fingerprint=_fingerprint(msg.text),
            excerpt=msg.text[:2000],
            trigger_name=names,
        ))
        for trigger in triggers:
            try:
                trigger.handle(msg)
            except Exception as exc:  # noqa: BLE001
                self._on_error(trigger.name, exc)
        return f"handled:{names}"


def ping_trigger(delivery, test_chat_guid: str) -> Trigger:
    def matches(msg: InboundMessage) -> bool:
        return msg.chat_guid == test_chat_guid and msg.text.strip().lower() == "bot: ping" and not msg.is_from_me

    def handle(msg: InboundMessage) -> None:
        delivery.deliver(None, "ping", f"pong {datetime.now(UTC).isoformat(timespec='seconds')}")

    return Trigger("ping", matches, handle)
```

- [ ] **Step 5: Implement the app and launcher**

```python
# packages/league-automation/src/ultimate_guillotine/listener/app.py
import secrets

from fastapi import FastAPI, HTTPException, Request

from ultimate_guillotine.messages.bluebubbles import parse_webhook


def create_app(processor, heartbeats, webhook_password: str) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.post("/bluebubbles-webhook")
    async def webhook(request: Request) -> dict:
        supplied = request.query_params.get("password") or request.headers.get("x-password") or ""
        if not secrets.compare_digest(supplied, webhook_password):
            raise HTTPException(status_code=401)
        payload = await request.json()
        heartbeats.beat("listener")
        msg = parse_webhook(payload)
        if msg is None:
            return {"outcome": "ignored_event"}
        return {"outcome": processor.process(msg, msg.guid)}

    return app
```

```python
# services/webhook-listener/main.py
"""Launch the BlueBubbles webhook listener. Supervised by launchd on the Mac mini."""
import httpx
import uvicorn

from ultimate_guillotine.config import DeliveryMode, load_settings
from ultimate_guillotine.data.database import connect
from ultimate_guillotine.data.repositories import (
    HeartbeatRepository,
    OutboundRepository,
    ReceiptRepository,
    SourceMessageRepository,
    TargetRepository,
)
from ultimate_guillotine.listener.app import create_app
from ultimate_guillotine.listener.processing import InboundProcessor, TriggerRegistry, ping_trigger
from ultimate_guillotine.messages.bluebubbles import BlueBubblesClient
from ultimate_guillotine.messages.delivery import DeliveryService
from ultimate_guillotine.ops.notify import HermesNotifier


class CommittingRepo:
    """Wrap a repository so every call commits; the listener runs one operation per request."""

    def __init__(self, repo, conn):
        self._repo, self._conn = repo, conn

    def __getattr__(self, name):
        method = getattr(self._repo, name)

        def call(*args, **kwargs):
            result = method(*args, **kwargs)
            self._conn.commit()
            return result

        return call


def main() -> None:
    settings = load_settings()
    if not settings.webhook_password or not settings.bluebubbles_password:
        raise SystemExit("WEBHOOK_PASSWORD and BLUEBUBBLES_PASSWORD are required")
    conn = connect(settings)
    client = BlueBubblesClient(settings.bluebubbles_server_url, settings.bluebubbles_password.get_secret_value(), httpx.Client())
    targets = TargetRepository(conn)
    allowed = {t.chat_guid for t in (targets.get(DeliveryMode.TEST), targets.get(DeliveryMode.PRODUCTION)) if t}
    notifier = HermesNotifier.from_settings(settings)
    delivery = DeliveryService(settings, client, targets, CommittingRepo(OutboundRepository(conn), conn), notifier)
    registry = TriggerRegistry()
    if settings.delivery_mode is DeliveryMode.TEST and settings.test_chat_guid:
        registry.register(ping_trigger(delivery, settings.test_chat_guid))
    processor = InboundProcessor(
        allowed, registry, CommittingRepo(ReceiptRepository(conn), conn), CommittingRepo(SourceMessageRepository(conn), conn),
        on_error=lambda name, exc: notifier.ops(f"listener trigger {name} failed: {exc.__class__.__name__}"),
    )
    app = create_app(processor, CommittingRepo(HeartbeatRepository(conn), conn), settings.webhook_password.get_secret_value())
    uvicorn.run(app, host=settings.webhook_listen_host, port=settings.webhook_listen_port, log_level="warning")


if __name__ == "__main__":
    main()
```

Agents from later plans register their triggers in this launcher next to `ping_trigger`.

- [ ] **Step 6: Run green and commit**

Run: `pnpm test:agents && pnpm lint:agents`

Expected: 8 listener tests PASS.

```bash
git add packages/league-automation/src/ultimate_guillotine/listener packages/league-automation/tests/listener services/webhook-listener
git commit -m "feat: add BlueBubbles webhook listener and inbound processor"
```

### Task 11: The `ug` command-line tool, health checks, and run audit

**Files:**
- Create: `packages/league-automation/src/ultimate_guillotine/ops/health.py`
- Create: `packages/league-automation/src/ultimate_guillotine/cli/__init__.py`
- Create: `packages/league-automation/src/ultimate_guillotine/cli/main.py`
- Create: `packages/league-automation/tests/ops/test_health.py`
- Create: `packages/league-automation/tests/cli/test_main.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `check_health(now, heartbeats, runs, expected, client) -> list[str]` returning human-readable problem lines, empty when healthy.
  - `ug ops heartbeat --component NAME`
  - `ug ops health [--escalate]`: prints problems; with `--escalate` also posts them to the alerts channel.
  - `ug ops audit-runs`: prints one line per expected job whose last `agent_runs.started_at` is older than `max_gap_minutes`.
  - `ug ops sync-expected-runs PATH`: loads `hermes/guillotine/cron.yaml` into `private.expected_runs`.
  - `ug ops self-test [--crash-after-send]`: reserves run `self-test` with key `self-test:<utc minute>` and delivers `Self-test <iso time>`.
  - `ug ops doctor`: prints PASS/FAIL per check, exit 1 on any FAIL.
  - `ug ops register-webhook`: calls `ensure_webhook` with the listener URL.
  - `ug ops fingerprint --chat-guid GUID`: prints the fingerprint of the chat's current participants.
  - `ug targets set --mode test|production --chat-guid GUID --label TEXT`: stores the target, computing the fingerprint for production.
  - `ug sleeper sync`
  - `ug ingest gap-fill [--since-minutes N]`: replays messages from each allowed chat through `InboundProcessor`.
  - `ug listener run`: same as `services/webhook-listener/main.py`.

- [ ] **Step 1: Write the failing health tests**

```python
# packages/league-automation/tests/ops/test_health.py
from datetime import UTC, datetime, timedelta

from ultimate_guillotine.data.repositories import ExpectedRun
from ultimate_guillotine.ops.health import check_health

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


class FakeBeats:
    def __init__(self, stale):
        self._stale = stale

    def stale(self, older_than, now):
        return self._stale


class FakeRuns:
    def __init__(self, last):
        self._last = last

    def last_started(self, agent):
        return self._last.get(agent)


class FakeExpected:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeClient:
    def __init__(self, ok):
        self._ok = ok

    def ping(self):
        return self._ok


def test_healthy_system_reports_nothing() -> None:
    expected = FakeExpected([ExpectedRun("guillotine-health", "health", 15, "every 5m")])
    runs = FakeRuns({"health": NOW - timedelta(minutes=4)})
    assert check_health(NOW, FakeBeats([]), runs, expected, FakeClient(True)) == []


def test_reports_stale_heartbeat_missed_run_and_bluebubbles() -> None:
    expected = FakeExpected([ExpectedRun("guillotine-health", "health", 15, "every 5m")])
    runs = FakeRuns({"health": NOW - timedelta(minutes=40)})
    problems = check_health(NOW, FakeBeats(["listener"]), runs, expected, FakeClient(False))
    assert any("listener" in p for p in problems)
    assert any("guillotine-health" in p and "40" in p for p in problems)
    assert any("BlueBubbles" in p for p in problems)


def test_never_run_job_is_reported() -> None:
    expected = FakeExpected([ExpectedRun("guillotine-gap-fill", "gap-fill", 15, "every 3m")])
    problems = check_health(NOW, FakeBeats([]), FakeRuns({}), expected, FakeClient(True))
    assert problems == ["Expected job guillotine-gap-fill has never run"]
```

- [ ] **Step 2: Write the failing CLI tests**

```python
# packages/league-automation/tests/cli/test_main.py
import subprocess
import sys


def test_ug_help_lists_commands() -> None:
    result = subprocess.run([sys.executable, "-m", "ultimate_guillotine.cli.main", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    for name in ("ops", "targets", "sleeper", "ingest", "listener"):
        assert name in result.stdout


def test_ops_health_help() -> None:
    result = subprocess.run([sys.executable, "-m", "ultimate_guillotine.cli.main", "ops", "health", "--help"], capture_output=True, text=True)
    assert "--escalate" in result.stdout
```

- [ ] **Step 3: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/ops/test_health.py packages/league-automation/tests/cli -v`

Expected: FAIL.

- [ ] **Step 4: Implement health**

```python
# packages/league-automation/src/ultimate_guillotine/ops/health.py
from datetime import datetime, timedelta

LISTENER_STALE_AFTER = timedelta(minutes=10)


def check_health(now: datetime, heartbeats, runs, expected, client) -> list[str]:
    problems: list[str] = []
    for component in heartbeats.stale(LISTENER_STALE_AFTER, now):
        problems.append(f"Heartbeat for {component} is stale")
    for job in expected.all():
        last = runs.last_started(job.agent)
        if last is None:
            problems.append(f"Expected job {job.job_name} has never run")
            continue
        age = int((now - last).total_seconds() // 60)
        if age > job.max_gap_minutes:
            problems.append(f"Expected job {job.job_name} last ran {age} minutes ago (limit {job.max_gap_minutes})")
    if not client.ping():
        problems.append("BlueBubbles server is not responding to ping")
    return problems
```

Every `ug` command that represents a scheduled job records a run: `RunRepository.reserve(agent, "cron", f"{agent}:{now:%Y%m%dT%H%M}")` and `finish(...)` at exit. That is what `last_started` reads. Agents are named `health`, `gap-fill`, `sleeper-sync`, `run-audit`, `self-test`, `ping`.

- [ ] **Step 5: Implement the CLI**

`cli/main.py` ends with `if __name__ == "__main__": main()` and uses `argparse` with subparsers `ops`, `targets`, `sleeper`, `ingest`, `listener`. Each subcommand function builds its dependencies from `load_settings()` and `connect()`, commits on success, and prints only non-secret text. Behaviors:

- `ops heartbeat`: `HeartbeatRepository.beat(component)`.
- `ops health`: `check_health(...)`; print each problem on its own line; with `--escalate` and any problems, also `notifier.alerts("\n".join(problems))`. Exit 0 either way so Hermes treats output as the report. Empty output means Hermes delivers nothing.
- `ops audit-runs`: same loop as health's expected-run section only, prefixed `Missed:`; exit 0.
- `ops sync-expected-runs PATH`: parse YAML `jobs[]`, build `ExpectedRun(name, agent, max_gap_minutes, schedule)`, `replace_all`.
- `ops self-test`: reserve run, `DeliveryService(..., crash_after_send=args.crash_after_send).deliver(run_id, "self-test", f"Self-test {now.isoformat(timespec='seconds')}")`, finish run, print `sent` or `reconciled` and the outbound id. Refuse with exit 2 when `delivery_mode` is `production`.
- `ops doctor`: checks, each printed as `PASS name` or `FAIL name: reason`: Python is 3.12; settings load; `delivery_mode` is not `disabled`; database `select 1`; BlueBubbles ping; BlueBubbles `server_info` reachable; a delivery target row exists for the configured mode and its GUID matches settings; listener health at `http://{host}:{port}/healthz`; listener heartbeat newer than 10 minutes; `hermes send --list` succeeds with `HERMES_HOME` set to the profile. Exit 1 on any FAIL.
- `ops register-webhook`: `client.ensure_webhook(f"http://{host}:{port}/bluebubbles-webhook?password={webhook_password}")`; print `webhook registered`.
- `ops fingerprint`: print `participant_fingerprint(client.chat_participants(guid))`.
- `targets set`: for production compute the fingerprint from live participants; call `TargetRepository.upsert`; print the target id only.
- `sleeper sync`: `sync_season(SleeperClient(httpx.Client()), conn, 2026, settings.sleeper_league_id)`; print counts.
- `ingest gap-fill`: for each allowed target, `since = sources.latest_sent_at(chat_guid_hash(guid)) or now - since_minutes`; for each `client.messages_after(guid, since)`, call `processor.process(msg, msg.guid)`; print one line `gap-fill: N messages, M handled`.
- `listener run`: import and call `services` launcher logic; to avoid a path dependency, move the body of `services/webhook-listener/main.py` into `ultimate_guillotine.listener.run:main` and have the service file import it.

- [ ] **Step 6: Run green and commit**

Run: `pnpm test:agents && pnpm lint:agents && uv run --project packages/league-automation ug --help`

Expected: tests PASS; help lists the five command groups.

```bash
git add packages/league-automation services
git commit -m "feat: add ug command-line tool with health and self-test"
```

### Task 12: Hermes profile assets and cron registration

**Files:**
- Create: `hermes/guillotine/SOUL.md`
- Create: `hermes/guillotine/cron.yaml`
- Create: `hermes/guillotine/register_cron.py`
- Create: `hermes/guillotine/install.sh`
- Create: `hermes/guillotine/scripts/guillotine_health.sh.template`
- Create: `hermes/guillotine/scripts/guillotine_gap_fill.sh.template`
- Create: `hermes/guillotine/scripts/guillotine_sleeper_sync.sh.template`
- Create: `hermes/guillotine/scripts/guillotine_run_audit.sh.template`
- Create: `hermes/guillotine/skills/guillotine-ops/SKILL.md`
- Create: `packages/league-automation/tests/hermes/test_register_cron.py`

**Interfaces:**
- Consumes: `ug` commands; Hermes CLI.
- Produces: an installed `guillotine` profile with four script-only cron jobs; `register_cron.plan(jobs_yaml: dict, existing_jobs: dict) -> list[list[str]]` returning the exact Hermes commands to run.

- [ ] **Step 1: Write the failing registration test**

```python
# packages/league-automation/tests/hermes/test_register_cron.py
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("register_cron", Path("hermes/guillotine/register_cron.py"))
register_cron = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(register_cron)

MANIFEST = {"jobs": [
    {"name": "guillotine-health", "agent": "health", "schedule": "every 5m", "script": "guillotine_health.sh", "deliver": "discord:#guillotine-ops", "max_gap_minutes": 15},
]}


def test_plan_creates_missing_job() -> None:
    commands = register_cron.plan(MANIFEST, existing_jobs={})
    assert commands == [["hermes", "cron", "create", "every 5m", "--name", "guillotine-health", "--script", "guillotine_health.sh", "--no-agent", "--deliver", "discord:#guillotine-ops"]]


def test_plan_edits_existing_job_by_name() -> None:
    commands = register_cron.plan(MANIFEST, existing_jobs={"guillotine-health": "abc123"})
    assert commands == [["hermes", "cron", "edit", "abc123", "--schedule", "every 5m", "--script", "guillotine_health.sh", "--no-agent", "--deliver", "discord:#guillotine-ops"]]


def test_existing_jobs_from_state_file() -> None:
    state = {"jobs": [{"id": "abc123", "name": "guillotine-health"}, {"id": "zzz", "name": "other"}]}
    assert register_cron.existing_from_state(state) == {"guillotine-health": "abc123", "other": "zzz"}
```

- [ ] **Step 2: Run red**

Run: `uv run --project packages/league-automation pytest packages/league-automation/tests/hermes -v`

Expected: FAIL, file missing.

- [ ] **Step 3: Write the manifest and registrar**

```yaml
# hermes/guillotine/cron.yaml
# Script-only jobs run repo CLIs with no language model in the loop.
# Empty stdout means Hermes delivers nothing; only problems reach Discord.
jobs:
  - name: guillotine-health
    agent: health
    schedule: "every 5m"
    script: guillotine_health.sh
    deliver: "discord:#guillotine-ops"
    max_gap_minutes: 15
  - name: guillotine-gap-fill
    agent: gap-fill
    schedule: "every 3m"
    script: guillotine_gap_fill.sh
    deliver: local
    max_gap_minutes: 15
  - name: guillotine-sleeper-sync
    agent: sleeper-sync
    schedule: "0 */6 * * *"
    script: guillotine_sleeper_sync.sh
    deliver: "discord:#guillotine-ops"
    max_gap_minutes: 420
  - name: guillotine-run-audit
    agent: run-audit
    schedule: "0 8 * * *"
    script: guillotine_run_audit.sh
    deliver: "discord:#guillotine-ops"
    max_gap_minutes: 1500
```

```python
# hermes/guillotine/register_cron.py
"""Register cron.yaml jobs with the guillotine Hermes profile. Idempotent by job name."""
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


def existing_from_state(state: dict) -> dict[str, str]:
    jobs = state.get("jobs", state)
    if isinstance(jobs, dict):
        jobs = list(jobs.values())
    return {j["name"]: j["id"] for j in jobs if isinstance(j, dict) and j.get("name") and j.get("id")}


def plan(manifest: dict, existing_jobs: dict[str, str]) -> list[list[str]]:
    commands = []
    for job in manifest["jobs"]:
        tail = ["--script", job["script"], "--no-agent", "--deliver", job["deliver"]]
        if job["name"] in existing_jobs:
            commands.append(["hermes", "cron", "edit", existing_jobs[job["name"]], "--schedule", job["schedule"], *tail])
        else:
            commands.append(["hermes", "cron", "create", job["schedule"], "--name", job["name"], *tail])
    return commands


def main() -> None:
    profile_home = Path(os.environ["HERMES_HOME"]).expanduser()
    manifest = yaml.safe_load(Path(sys.argv[1]).read_text())
    state_path = profile_home / "cron" / "jobs.json"
    existing = existing_from_state(json.loads(state_path.read_text())) if state_path.exists() else {}
    for command in plan(manifest, existing):
        print(" ".join(command))
        subprocess.run(command, check=True, env={**os.environ, "HERMES_HOME": str(profile_home)})


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Write the script templates, SOUL, skill, and installer**

Each template is identical apart from the `ug` command; `__REPO__` is replaced at install time:

```bash
# hermes/guillotine/scripts/guillotine_health.sh.template
#!/bin/bash
set -euo pipefail
cd "__REPO__"
exec /opt/homebrew/bin/uv run --project packages/league-automation ug ops health --escalate
```

The other three end with `ug ingest gap-fill`, `ug sleeper sync`, and `ug ops audit-runs`.

`SOUL.md` states: you are Guillotine Ops, the private operations assistant for the Ultimate Guillotine fantasy league; you talk only to Ben in Discord; you run league commands through the `guillotine-ops` skill; you never post to iMessage and have no iMessage tools; you never reveal chat identifiers, phone numbers, or secrets; when asked about status you run `ug ops health` and `hermes cron list` and summarize.

`skills/guillotine-ops/SKILL.md` documents, with the exact commands, how to run `ug ops health`, `ug ops audit-runs`, `ug ops self-test`, `ug ops doctor`, and `ug sleeper sync` from the repository directory, and that all of them are safe to re-run.

```bash
# hermes/guillotine/install.sh
#!/bin/bash
# Idempotent: creates the guillotine Hermes profile, syncs SOUL/skills/scripts, registers cron jobs.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PROFILE=guillotine
export HERMES_HOME="$HOME/.hermes/profiles/$PROFILE"

if [ ! -d "$HERMES_HOME" ]; then
  hermes profile create "$PROFILE" --no-skills --description "Ultimate Guillotine league operations: runs league CLIs, reports status to Ben in Discord"
fi
mkdir -p "$HERMES_HOME/skills/guillotine-ops" "$HERMES_HOME/scripts"
cp "$REPO/hermes/guillotine/SOUL.md" "$HERMES_HOME/SOUL.md"
cp "$REPO/hermes/guillotine/skills/guillotine-ops/SKILL.md" "$HERMES_HOME/skills/guillotine-ops/SKILL.md"
for template in "$REPO"/hermes/guillotine/scripts/*.sh.template; do
  target="$HERMES_HOME/scripts/$(basename "${template%.template}")"
  sed "s#__REPO__#$REPO#g" "$template" > "$target"
  chmod 755 "$target"
done
cd "$REPO"
uv run --project packages/league-automation python hermes/guillotine/register_cron.py hermes/guillotine/cron.yaml
uv run --project packages/league-automation ug ops sync-expected-runs hermes/guillotine/cron.yaml
echo "Profile $PROFILE installed. Next: paste DISCORD_BOT_TOKEN into $HERMES_HOME/.env, then run: HERMES_HOME=$HERMES_HOME hermes gateway install"
```

- [ ] **Step 5: Run green, lint the shell, and commit**

Run: `pnpm test:agents && pnpm lint:agents && bash -n hermes/guillotine/install.sh && for f in hermes/guillotine/scripts/*.template; do bash -n "$f"; done`

```bash
git add hermes packages/league-automation/tests/hermes
git commit -m "feat: add guillotine Hermes profile assets and cron registration"
```

### Task 13: Mac mini installation, launchd, and Gate 0

**Files:**
- Create: `scripts/mac-mini/com.ultimateguillotine.listener.plist.template`
- Create: `scripts/mac-mini/install_listener.sh`
- Create: `docs/runbooks/mac-mini.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above, the hosted Supabase project, BlueBubbles Server, a second Discord bot.
- Produces: a running listener under `launchd`, a running `guillotine` gateway, and a passed Gate 0.

- [ ] **Step 1: Write the plist template and installer**

```xml
<!-- scripts/mac-mini/com.ultimateguillotine.listener.plist.template -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ultimateguillotine.listener</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/uv</string>
    <string>run</string>
    <string>--project</string>
    <string>packages/league-automation</string>
    <string>ug</string>
    <string>listener</string>
    <string>run</string>
  </array>
  <key>WorkingDirectory</key><string>__REPO__</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>__HOME__/Library/Logs/UltimateGuillotine/listener.out.log</string>
  <key>StandardErrorPath</key><string>__HOME__/Library/Logs/UltimateGuillotine/listener.err.log</string>
</dict>
</plist>
```

```bash
# scripts/mac-mini/install_listener.sh
#!/bin/bash
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL=com.ultimateguillotine.listener
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/Logs/UltimateGuillotine" "$HOME/Library/LaunchAgents"
sed -e "s#__REPO__#$REPO#g" -e "s#__HOME__#$HOME#g" "$REPO/scripts/mac-mini/$LABEL.plist.template" > "$PLIST"
plutil -lint "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL"
echo "listener installed; check $HOME/Library/Logs/UltimateGuillotine/listener.err.log"
```

Run: `plutil -lint scripts/mac-mini/com.ultimateguillotine.listener.plist.template` is expected to fail on the placeholders, so lint the rendered file only, as the installer does. Run `bash -n scripts/mac-mini/install_listener.sh`.

- [ ] **Step 2: Write the runbook**

`docs/runbooks/mac-mini.md` covers, in order, with exact commands and no secret values:

1. Hosted Supabase: Ben creates the free project under his personal account; run `supabase link --project-ref <ref>` then `supabase db push`; run `scripts/configure_worker_role.sql.example` interactively; write `DATABASE_URL` for the `ultimate_guillotine_mac` login into the repo `.env`.
2. BlueBubbles Server: download from bluebubbles.app, sign in Messages.app with Ben's Apple ID, grant Full Disk Access and Automation when prompted, set a server password, leave the Private API off, note the local URL (default `http://127.0.0.1:1234`), and write `BLUEBUBBLES_SERVER_URL` and `BLUEBUBBLES_PASSWORD` into `.env`. Generate `WEBHOOK_PASSWORD` with `openssl rand -hex 24`.
3. Self-test chat: create a group iMessage chat containing Ben and one other Ben-controlled handle, find its GUID with `POST /api/v1/chat/query` through `curl` piped to `python3 -m json.tool`, and store it with `ug targets set --mode test --chat-guid "<guid>" --label self-test`. Set `DELIVERY_MODE=test` and `TEST_CHAT_GUID` in `.env`. Record that member phone numbers live only in BlueBubbles and `.env`.
4. Listener: `scripts/mac-mini/install_listener.sh`, then `ug ops register-webhook`.
5. Discord: create the four channels in Agent HQ; create a second bot application named Guillotine Ops in the Discord Developer Portal with Message Content and Server Members intents; invite it with View Channels, Send Messages, Read Message History, Attach Files; run `hermes/guillotine/install.sh`; paste `DISCORD_BOT_TOKEN`, `DISCORD_HOME_CHANNEL` (the ops channel id), and `DISCORD_ALLOWED_USERS` (Ben's user id) into `~/.hermes/profiles/guillotine/.env`; run `HERMES_HOME=~/.hermes/profiles/guillotine hermes gateway install`; confirm `hermes gateway list` shows both profiles running.
6. Gate 0 checks, as listed in Step 4 below.
7. Recovery: how to re-run a missed job with `/cron run` from Discord, how to read listener logs, how to rotate the BlueBubbles password.

- [ ] **Step 3: Perform the installation on the Mac mini**

Follow runbook sections 1 through 5. Ben performs the dashboard, Apple permission, and Discord token steps; everything else runs from this repository. After each section run `uv run --project packages/league-automation ug ops doctor` and continue only when the checks for that section report PASS.

- [ ] **Step 4: Run Gate 0**

1. Delivery: `ug ops self-test` prints `sent`; exactly one signed `Self-test ...` message appears in the self-test chat; `#guillotine-feed` shows the mirror.
2. Inbound: send `bot: ping` in the self-test chat from the non-Ben handle; a signed `pong ...` reply arrives within 10 seconds; `#guillotine-feed` shows it.
3. Scheduler: `HERMES_HOME=~/.hermes/profiles/guillotine hermes cron run <id of guillotine-health>` completes with status `ok` in `hermes cron list`, and `#guillotine-ops` receives either nothing or a problem list; `ug ops audit-runs` prints nothing for `guillotine-health`.
4. Crash replay: `ug ops self-test --crash-after-send` exits non-zero after one message is sent; run `ug ops self-test` again within the same minute; it prints `reconciled`; the chat shows exactly one new message for that minute.
5. Webhook replay: re-send the last webhook payload with `curl` from the listener log's recorded GUID; the response is `{"outcome":"duplicate"}`.
6. Gap fill: stop the listener with `launchctl bootout gui/$(id -u)/com.ultimateguillotine.listener`, send `bot: ping` in the self-test chat, restart with the installer, run `ug ingest gap-fill`; exactly one `pong` arrives and a second `ug ingest gap-fill` handles zero messages.
7. Doctor: `ug ops doctor` exits 0.

Record the outcomes in `docs/runbooks/mac-mini.md` under a "Gate 0 passed" heading with the date and delivery mode. Do not record GUIDs or handles.

- [ ] **Step 5: Run the foundation verification suite**

```bash
pnpm test:agents
pnpm lint:agents
supabase db reset
supabase test db
supabase db advisors
pnpm build
git diff --check
```

Expected: all exit 0; no unexplained security advisor finding.

- [ ] **Step 6: Commit**

```bash
git add scripts/mac-mini docs/runbooks README.md
git commit -m "feat: install listener under launchd and pass Gate 0"
```

---

## Self-Review Notes

- Spec coverage: profile and cron (Task 12), create-validate-send pattern is exercised by `deliver()` and left for agent plans to call, Discord channels (Tasks 8, 13), data model (Tasks 3, 4), access control (Tasks 1, 4, 13), ingestion and gap fill (Tasks 10, 11), safe delivery (Task 9), Sleeper (Task 6), observability (Task 11), Gate 0 (Task 13). The survival projection contract and knowledge sources have tables only; their logic belongs to the Game Pulse and Concierge plans.
- Names are consistent across tasks: `DeliveryTarget`, `OutboundRecord`, `SourceMessage`, `ExpectedRun`, `chat_guid_hash`, `content_hash`, `participant_fingerprint`, `InboundMessage`, `parse_webhook`, `HermesNotifier.feed/ops/alerts`, `check_health`, `InboundProcessor.process`.
- `ExpectedRunRepository.replace_all` needs `delete`, which `automation_worker` lacks. `install.sh` runs it under the developer login from the repo `.env`; the runbook must note that the install step uses that login, and the cron jobs never call it.
