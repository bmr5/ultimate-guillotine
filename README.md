# Ultimate Guillotine

Ultimate Guillotine is the shared home for the fantasy football league website, authoritative rules and contracts, historical records, private league-member data, automation agents, and maintenance scripts.

## Workspace layout

```text
apps/web/                  React and Vite website
agents/                    Future recap, research, and messaging agents
data/private/              Local-only member and contact data
docs/contracts/            Contract reference documents
docs/rules/                Authoritative league rules
history/contracts/         Historical contract workbooks by season
history/league/            Sanitized league history
scripts/                   Imports and future scheduled operations
```

The repository intentionally has no empty `packages/` directory. Shared packages should be introduced only after multiple applications or agents need the same code.

## Website

Install dependencies and run the existing site from the repository root:

```bash
pnpm install
pnpm dev
```

Production and static checks:

```bash
pnpm build
pnpm lint
```

The root commands delegate to the `@ultimate-guillotine/web` workspace in `apps/web`.

## League records

The tracked workbook at `history/league/ultimate-guillotine-records.xlsx` contains the non-private historical sheets. The old `2022` registration sheet is deliberately excluded because it contains member contact and registration information.

To regenerate both outputs from an original workbook:

```bash
python3 -m pip install -r scripts/requirements.txt
python3 scripts/import_league_records.py \
  "/path/to/Ultimate Guillotine Records.xlsx" \
  --sanitized-output history/league/ultimate-guillotine-records.xlsx \
  --private-output data/private/league-members.json
```

Run the automated importer tests and privacy check:

```bash
pnpm test:records
pnpm check:records
```

## Privacy

`data/private/league-members.json` contains real names, contact information, payment status, and registration responses. It is ignored by Git and must never be copied into public website assets, committed prompts, fixtures, logs, or generated recaps.

Use `data/private/league-members.example.json` for development that does not need real league data.

## 2026 dues tracker

Launch the private commissioner dues page:

```bash
pnpm dues
```

The tracker opens at `http://127.0.0.1:8765`, shows the latest roster, and saves Venmo handles, paid status, timestamps, and notes to ignored `data/private/dues-2026.json`. It is available only on the local Mac unless you deliberately build a separate authenticated remote-access layer.

## League automation

The `packages/league-automation` workspace contains Python agents and automation scripts for the Ultimate Guillotine league.

### Local database setup

Start Docker Desktop and the local Supabase stack:

```bash
open -a Docker
supabase start
```

Reset the database and run database tests:

```bash
supabase db reset
supabase test db
```

Repository tests (via `pnpm test:agents`) read the `TEST_DATABASE_URL` environment variable to connect to the local database. Tests are skipped when the environment variable is unset. Project credentials (API keys, database passwords) live outside Git in the local `.env` file or environment variables.

## Automation direction

The always-on Mac mini can eventually run scripts and agents for weekly recaps, daily league monitoring, and approved message delivery. Each external integration should begin in dry-run mode, keep secrets outside Git, and separate content generation from the action that sends a message.
