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

## Automation direction

The always-on Mac mini can eventually run scripts and agents for weekly recaps, daily league monitoring, and approved message delivery. Each external integration should begin in dry-run mode, keep secrets outside Git, and separate content generation from the action that sends a message.
