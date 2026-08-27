# Ultimate Guillotine Automation Foundation

## Objective

Build a Supabase-backed automation platform for the 2026 Ultimate Guillotine League. An always-on Mac mini ingests and sends iMessages using Ben Ray's Messages identity, while Supabase is the durable system of record, scheduler, queue, and website data source.

The foundation supports five independently deployable agents:

1. Trade Registrar
2. Weekly Adjudicator
3. Game Pulse
4. Weekly Storyteller
5. League Concierge

## Approved Decisions

- Supabase, not a local SQLite database, is the authoritative database.
- The Mac mini is a resumable worker for macOS-only integration and agent execution.
- Agents may post automatically after passing end-to-end tests in a dedicated self-test iMessage chat.
- Production posts use Ben's iMessage identity and end with `— 🤖 Guillotine Bot`.
- Agent delivery modes are `disabled`, `test`, and `production`, configured independently.
- There are no per-member bot rate limits.
- Deterministic code decides league state. Language models extract or generate language but do not decide cuts, gulag outcomes, scores, or standings.
- The authoritative 2026 Sleeper league is `1389372259260452864` (`Ultimate Guillotine League`, 18 teams).

## Architecture

```text
Supabase Cron ──> Supabase Queue ──> Mac mini worker ──> agent runtime
      │                   │                │                  │
      │                   │                ├─> Sleeper API    │
      │                   │                ├─> Messages DB    │
      │                   │                └─> Messages send <┘
      │                   │
      └────────────> Supabase Postgres <──────────── website
```

Supabase Cron creates scheduled work. A durable Supabase Queue retains jobs while the Mac is asleep, offline, or restarting. The Mac worker consumes jobs, reads required inputs, runs deterministic or AI-assisted logic, and sends approved output through Messages. Every run and delivery is recorded in Supabase.

`launchd` starts and supervises the Mac worker after login or reboot. The worker holds no authoritative local state. Its source cursors, leases, run history, and delivery records are stored in Supabase.

## Repository Boundaries

Implementation will use these top-level areas:

```text
agents/
  shared/                 # runtime contracts, prompts, event types, delivery policy
  trade-registrar/
  weekly-adjudicator/
  game-pulse/
  weekly-storyteller/
  league-concierge/
packages/
  league-core/            # deterministic rules and shared domain types
  sleeper-client/         # read-only Sleeper adapter
  supabase-data/          # generated types and repositories
services/
  mac-worker/             # Messages ingestion/sending and queue consumer
supabase/
  migrations/             # reviewed database migrations
  seed.sql                 # non-secret local development fixtures
scripts/
  mac-mini/               # installation, launchd, permission, and health scripts
```

The existing website remains under `apps/web`. Shared packages are introduced only when the foundation implementation begins and two consumers genuinely share the code.

## Supabase Data Model

All identifiers use lowercase snake_case. Timestamps are `timestamptz`. Monetary and FAAB amounts are exact numeric or integer values, never floats. Foreign keys are indexed.

### Public league tables

- `seasons`: season number, Sleeper league ID, phase, and rules version.
- `members`: league display identity only; no contact fields.
- `teams`: season membership, Sleeper user ID, roster ID, and public team name.
- `weekly_results`: finalized and corrected scoring outcomes by season and week.
- `league_events`: immutable public events such as trades, gulag entry, elimination, cut, and championship.
- `trades`: current normalized public trade record.
- `trade_revisions`: immutable history of materially changed terms.
- `survival_snapshots`: timestamped team position and survival estimates with model/input version.
- `recaps`: generated daily or weekly posts and their publication state.

### Private operational tables

These live in an unexposed `private` schema:

- `member_contacts`: ignored/private member contact import and iMessage aliases.
- `delivery_targets`: hashed chat identity, exact chat GUID, participant-set fingerprint, and delivery mode.
- `source_cursors`: the last processed Messages row/GUID for each permitted chat.
- `source_messages`: qualifying message metadata and relevant excerpts only.
- `agent_runs`: agent, trigger, idempotency key, input version, status, attempts, output hash, and errors.
- `outbound_messages`: target, signed content, content hash, reservation time, send time, and reconciliation state.
- `projection_snapshots`: provider payload normalized for survival calculations.
- `knowledge_sources`: versioned rules, contracts, and historical source metadata.

The queue uses a durable Supabase Queue backed by `pgmq`. Queue payloads contain references and idempotency keys, not secrets or full chat archives.

### Immutability and corrections

League facts are append-oriented. A correction creates a compensating event and a new state version rather than erasing the original event. Mutable summary tables such as `trades` point to the latest accepted revision while immutable revision and event tables retain the audit trail.

## Access Control and Secrets

- Enable Row Level Security on every table in an exposed schema.
- Anonymous website access may read only explicitly public league tables.
- A dedicated Supabase Auth identity represents the Mac worker. Authorization is stored in app metadata, not user-editable metadata.
- The worker receives only the grants and Queue operations it needs. It does not use a database superuser.
- Supabase secret/service credentials, Apple automation configuration, AI credentials, and chat GUIDs live in macOS Keychain or ignored local environment files.
- No secret key is bundled into the website.
- Views exposed to the website use `security_invoker = true`.
- The tracked `apps/web/.env.example` value named `SupaBasePass` is treated as compromised, rotated before reconnection, removed from Git-tracked examples, and replaced only in secure local configuration.

## iMessage Ingestion

The Mac worker receives Full Disk Access so it can read the local Messages database. It reads only allowlisted chats and advances a Supabase cursor after successfully persisting message metadata.

For ordinary chat messages, the system stores the Apple message GUID, sender mapping, timestamp, direction, chat target, and content fingerprint. Raw unrelated conversation is not uploaded to Supabase. Relevant text is retained only for trade evidence, bot questions, answers, or selected recap candidates.

Messages sent by the bot are ignored as inbound triggers when any of these conditions apply:

- the message is from Ben and has a matching outbound reservation;
- the message ends with the bot signature;
- the Apple message GUID was previously reconciled to an outbound record.

## Safe iMessage Delivery

Delivery targets are addressed by exact chat GUID and verified participant-set fingerprint, not mutable chat name. Test mode can send only to the self-test chat. Production mode can send only to the approved league chat.

Delivery is effectively-once across the external Messages boundary:

1. Claim the queue message with a visibility lease.
2. Insert an `agent_runs` row using a unique idempotency key.
3. Reserve the exact signed outbound content.
4. Recheck the target GUID, participant fingerprint, and agent delivery mode.
5. Send through the Messages AppleScript `send` command.
6. Record the successful delivery and archive the queue message.
7. If the worker crashes after sending but before recording success, inspect recent sent Messages for the same target and content hash before retrying.

The sender never silently falls back from the test target to the production target.

## Sleeper Synchronization

The Sleeper adapter uses the official read-only API for league metadata, users, rosters, matchups, transactions, drafts, and NFL state. Ben's stable Sleeper user ID may be used to discover the active seasonal league, but the discovered league must match the configured league name and 18-team expectation before becoming active.

Raw snapshots include fetch time and source endpoint. Normalization maps Sleeper user and roster IDs to stable league member IDs. A sync does not infer elimination state; the deterministic rules engine derives league events from normalized scores plus accepted overrides.

## Survival Projection Contract

Survival calculations consume a provider-neutral projection interface. Reconnection first audits the existing Supabase `player_projections` data. It is accepted for 2026 only if it is current and covers at least 95 percent of rostered, unplayed starters in a validation week.

If that coverage gate fails, Game Pulse may post factual standings but must omit survival percentages until a replacement projection provider passes the same gate. Missing data is never converted into zero projected points.

Every survival snapshot records the projection source, source timestamp, simulation version, number of simulations, and input hash.

## AI Boundary

AI may:

- turn a qualifying trade alert into proposed structured terms;
- write narrative recaps from structured facts;
- select from prefiltered chat-highlight candidates;
- answer a tagged question using retrieved league sources.

AI may not:

- choose the weekly low score or rank teams;
- decide gulag entry, elimination, or cuts;
- silently resolve ambiguous trade terms;
- modify source facts, rules, rosters, or scores;
- expose private contacts, dues notes, secrets, or unrelated chat.

All prompts and model settings are versioned. Agent runs record the prompt version and source-event IDs used.

## Scheduling and Time

All stored times use UTC. Rule deadlines display in `America/Chicago`, matching the rule document. Mac operations and direct commissioner alerts may additionally show `America/Los_Angeles`.

Event-driven work is queued by the Mac message watcher or Sleeper synchronizer. Scheduled work is enqueued by Supabase Cron. Cron creates work; the Mac performs iMessage delivery.

## Observability and Failure Handling

- The Mac worker writes a heartbeat to Supabase at least once per minute.
- A health job detects stale heartbeats, missed scheduled runs, expired leases, repeated model failures, and Messages permission failures.
- Operational alerts go to the self-test/direct commissioner chat, never the league chat.
- Jobs use bounded exponential retry. Permanent validation errors enter a failed state with actionable context.
- League-facing agents omit unavailable sections rather than inventing data.
- Supabase and Messages outages preserve queued work for replay.

## Rollout Gates

Each agent progresses independently:

1. Fixture tests with recorded, anonymized inputs.
2. Dry run with persisted output and no Messages send.
3. End-to-end delivery to the self-test chat.
4. At least one successful replay/duplicate test.
5. Production mode enabled explicitly for that agent.

The first production agent will be Trade Registrar because its trigger is narrow and its output is easy to audit. Weekly Adjudicator follows after deterministic historical replay. Narrative and interactive agents follow after the shared factual layer is stable.

## Out of Scope

- Modifying Sleeper rosters or scores through automation.
- Sending from a separate Apple identity.
- Running an authoritative local database.
- Automatically changing league rules from chat discussion.
- Guaranteeing a projection percentage when projection coverage is below the approved threshold.

