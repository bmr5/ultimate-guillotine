# Ultimate Guillotine Automation Foundation

> **Revision 2026-09-08.** This revision replaces the original Supabase Cron, Supabase Queue, and custom Mac worker runtime with the Hermes Agent gateway already running on the Mac mini, BlueBubbles for iMessage transport, and a private Discord server as the operations console. Supabase remains the system of record. The five agent specs are unchanged except for the trigger wording in Trade Registrar and League Concierge.

## Objective

Build a Supabase-backed automation platform for the 2026 Ultimate Guillotine League. An always-on Mac mini sends and receives iMessages using Ben Ray's Messages identity through BlueBubbles, Hermes Agent schedules and supervises all recurring work, and Ben checks on every agent and loop, and manages the league when needed, from Discord on his phone.

The foundation supports five independently deployable agents:

1. Trade Registrar
2. Weekly Adjudicator
3. Game Pulse
4. Weekly Storyteller
5. League Concierge

It also supports an open-ended set of future "fun" agents and loops that follow the same create-validate-send pattern.

## Approved Decisions

- Supabase, not a local SQLite database, is the authoritative database for league state, run history, and idempotency.
- The league chat is iMessage and only iMessage. League members are never asked to join Discord.
- Discord is Ben's private operations console, not a league surface. The existing `Agent HQ` server hosts it.
- Hermes Agent on the Mac mini is the scheduler, supervisor, and human interface for all automation. Claude Code loops and Grok bots are not part of the runtime.
- BlueBubbles Server on the Mac mini is the only iMessage transport. The repository's delivery layer is the only code that talks to it for the league chat. Hermes's built-in BlueBubbles adapter stays disabled.
- Nothing with a language model in the loop has a direct line to the league chat. Every league-facing message passes through the repository's deterministic delivery layer.
- Agents may post automatically after passing end-to-end tests in a dedicated self-test iMessage chat.
- Production posts use Ben's iMessage identity and end with `— 🤖 Guillotine Bot`.
- Agent delivery modes are `disabled`, `test`, and `production`, configured independently.
- There are no per-member bot rate limits.
- Deterministic code decides league state. Language models extract or generate language but do not decide cuts, gulag outcomes, scores, or standings.
- The authoritative 2026 Sleeper league is `1389372259260452864` (`Ultimate Guillotine League`, 18 teams).

## Architecture

```text
                    ┌──────────────── Mac mini (always on) ────────────────┐
                    │                                                        │
 Discord (Ben) <──> │ Hermes gateway ── profile: guillotine                  │
   #guillotine-ops  │   ├─ cron (script-only) ──> repo CLIs ──┐              │
   #guillotine-feed │   ├─ cron (agent-mode)  ──> drafts ─────┤              │
   #guillotine-drafts   └─ /cron, /kanban, plain-English ops  │              │
                    │                                          ▼              │
                    │ launchd: webhook listener ──> deterministic triggers    │
                    │   ▲                              │                      │
                    │   │ webhook                      ▼                      │
                    │ BlueBubbles Server <──── delivery layer (REST send)     │
                    │   ▲          │                   │                      │
                    └───┼──────────┼───────────────────┼──────────────────────┘
                        │          ▼                   ▼
                  Messages.app  league / self-test   Supabase Postgres <── website
                                 iMessage chats       (system of record)
                                                       ▲
                                                  Sleeper API (read-only)
```

Three processes run on the Mac mini:

1. **BlueBubbles Server** bridges Messages.app. It holds the Full Disk Access and Automation permissions, receives new messages, and exposes a local REST API for sending.
2. **Hermes gateway (`guillotine` profile)** runs scheduled work through its cron subsystem, connects to Discord, and records run history. It is supervised by `launchd` and already survives reboots.
3. **Webhook listener** is a small repository-owned process, supervised by `launchd`, that receives BlueBubbles webhooks, applies deterministic trigger rules, and runs event-driven agents inline.

Scheduled agents are Hermes cron jobs that invoke repository command-line entry points. Event-driven agents run from the webhook listener. Both record every run and delivery in Supabase. The Mac mini holds no authoritative local state.

## Repository Boundaries

Implementation uses these top-level areas:

```text
agents/
  shared/                 # runtime contracts, prompts, event types, delivery policy
  trade-registrar/
  weekly-adjudicator/
  game-pulse/
  weekly-storyteller/
  league-concierge/
packages/
  league-automation/      # one Python distribution with focused modules
    src/ultimate_guillotine/
      core/               # deterministic rules and shared domain types
      sleeper/            # read-only Sleeper adapter
      data/               # Postgres repositories and generated types
      messages/           # BlueBubbles REST client, webhook models, delivery policy
      cli/                # one entry point per agent plus shared ops commands
services/
  webhook-listener/       # BlueBubbles webhook receiver and event-driven agent runner
hermes/
  guillotine/             # the Hermes profile, versioned
    SOUL.md               # persona and standing instructions for the ops profile
    skills/               # Hermes skills that wrap repo CLIs for agent-mode jobs
    cron.yaml             # declarative cron manifest (name, schedule, command, delivery)
    install.sh            # idempotent: create profile, sync skills, register cron jobs
supabase/
  migrations/             # reviewed database migrations
  seed.sql                # non-secret local development fixtures
scripts/
  mac-mini/               # BlueBubbles setup, launchd, permission, and health scripts
```

The existing website remains under `apps/web`. The Python boundaries begin as focused modules in one installable distribution; they split into independent packages only if deployment or ownership later requires it.

Everything Hermes needs is versioned under `hermes/guillotine/` and applied to the Mac mini by the install script. Hand edits inside `~/.hermes/profiles/guillotine/` are not the source of truth.

## Hermes Runtime

### Profile

A dedicated Hermes profile named `guillotine` runs the league. Profiles are isolated Hermes homes with their own config, memory, sessions, skills, cron jobs, and gateway process. The default profile on the Mac mini is Ben's personal agent and hosts unrelated jobs; the league never shares it.

The `guillotine` profile:

- runs its own gateway process under `launchd`, alongside the default profile's gateway;
- uses its own Discord bot application and token, because Hermes refuses to run two profiles on one token;
- has no BlueBubbles platform configured, so it cannot read or post to any iMessage chat directly;
- pins its cron model explicitly, because Hermes skips unpinned jobs when the global model changes.

Hermes Bot Mode, which presents profiles as named bots in Hermes Desktop, is optional. Nothing in this design depends on Hermes Desktop being installed.

### Scheduled work

Every scheduled agent is a Hermes cron job declared in `hermes/guillotine/cron.yaml` and registered by the install script. Jobs come in two modes:

- **Script-only jobs** run a repository CLI with no language model in the Hermes loop. Weekly Adjudicator, Game Pulse, Sleeper synchronization, projection refresh, and health audits are script-only. Standard output is delivered to a Discord ops channel; the CLI itself sends any league-facing message through the delivery layer.
- **Agent-mode jobs** let the Hermes agent think and write, using skills that wrap repository CLIs. Weekly Storyteller drafting and future fun loops are agent-mode. Their output is a draft, never a send.

The cron subsystem is a scheduler with a grace window, not a durable queue. If the Mac mini is down when a job is due, the job may be skipped rather than replayed. Three safeguards make that acceptable on an always-on machine:

1. Every CLI is idempotent and safe to re-run at any time.
2. Supabase `agent_runs` records what actually ran, so a re-run detects prior success.
3. A daily script-only audit job compares expected runs with recorded runs and reports gaps to `#guillotine-ops`, where Ben can trigger the missed job from his phone with `/cron run`.

Supabase Cron and Supabase Queue are not used. The `pgmq` extension is not enabled.

### Create, validate, send

Any agent that uses a language model follows one pattern, whether it runs inside Hermes or inside a repository CLI:

1. A repository CLI produces a structured fact packet from Supabase.
2. The model writes from that packet only.
3. A repository CLI validates the draft against the packet, applies the delivery policy, and either sends through the delivery layer or rejects the draft with reasons.

For agent-mode Hermes jobs, step 3 is a `submit` command. A rejected draft is posted to `#guillotine-drafts` with the validation errors and is never sent. This is how "tons of agents" can be added later without any of them gaining a path to the league chat.

## Discord Operations Console

Discord is where Ben checks on every agent and loop and manages the league from mobile. It is never a league member surface.

Channels in the `Agent HQ` server, readable only by Ben:

- `#guillotine-ops`: every run outcome, health audit, missed-run report, heartbeat gap, permission failure, and permanent error. This is the channel to glance at.
- `#guillotine-feed`: a mirror of every message actually delivered to the league chat, with agent, mode, and run ID. This is how Ben confirms what the league saw without opening Messages.
- `#guillotine-drafts`: previews from agents in `test` mode, rejected drafts with validation errors, and anything awaiting a commissioner decision.
- `#guillotine-alerts`: the "commissioner channel" referenced by the agent specs. Only conditions that need a human today, such as an unresolved weekly state, a trade clarification that timed out, or a stale heartbeat. Ben enables push notifications for this channel alone.

Operations from the phone:

- `/cron list` and `/cron run <job>` on the `guillotine` profile show and trigger scheduled agents.
- Plain-English requests to the profile, such as "dry-run the adjudicator for week 3" or "show me the last game pulse", run repository CLIs through skills and reply in the thread.
- Commissioner actions such as accepting a score override, resolving a tie, or approving a trade clarification are repository CLIs exposed as skills. They require Ben's Discord user ID, and the CLI records who invoked them in Supabase.

The Hermes web dashboard binds to loopback only. It is an optional desktop view, reachable from a phone only over Tailscale, and nothing in this design requires it.

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
- `source_messages`: qualifying message metadata and relevant excerpts only, keyed by Apple message GUID.
- `webhook_receipts`: BlueBubbles event ID, receipt time, and processing outcome, so replayed webhooks are ignored.
- `agent_runs`: agent, trigger, idempotency key, input version, status, attempts, output hash, invoking Discord user when applicable, and errors.
- `outbound_messages`: target, signed content, content hash, reservation time, send time, BlueBubbles message GUID, and reconciliation state.
- `projection_snapshots`: provider payload normalized for survival calculations.
- `knowledge_sources`: versioned rules, contracts, and historical source metadata.
- `expected_runs`: the schedule the daily audit compares against, derived from the cron manifest at install time.

### Immutability and corrections

League facts are append-oriented. A correction creates a compensating event and a new state version rather than erasing the original event. Mutable summary tables such as `trades` point to the latest accepted revision while immutable revision and event tables retain the audit trail.

## Access Control and Secrets

- Enable Row Level Security on every table in an exposed schema.
- Anonymous website access may read only explicitly public league tables.
- A dedicated least-privilege Postgres login represents the Mac mini automation through Supavisor. Its password is generated during deployment and stored only in macOS Keychain.
- The login inherits an `automation_worker` role with only the private-table operations it needs. It does not use `postgres`, a database superuser, or the browser-facing Supabase secret key.
- Supabase credentials, the BlueBubbles server password, AI credentials, and chat GUIDs live in macOS Keychain or ignored local environment files. Repository CLIs read them from the environment that `launchd` and the Hermes profile provide.
- The `guillotine` profile's Discord bot token lives in that profile's `.env` on the Mac mini, never in the repository.
- BlueBubbles keeps its own allowlist of member handles on the Mac mini. That is the one place member phone numbers exist outside `data/private/`, and it is documented in the Mac mini runbook.
- No secret key is bundled into the website.
- Views exposed to the website use `security_invoker = true`.
- The tracked `apps/web/.env.example` value named `SupaBasePass` is treated as compromised, rotated before reconnection, removed from Git-tracked examples, and replaced only in secure local configuration.

## iMessage Ingestion

BlueBubbles Server holds Full Disk Access and reads the Messages database. It posts a webhook to the repository's listener on loopback for every new message. The listener does not poll the Messages database and does not need Full Disk Access.

The listener:

1. verifies the webhook came from the local BlueBubbles server;
2. records the event in `webhook_receipts` and drops it if already seen;
3. ignores any chat whose GUID is not an allowlisted delivery target;
4. applies deterministic trigger rules per agent, such as the red alert emoji for Trade Registrar or a bot tag for League Concierge;
5. persists qualifying message metadata to `source_messages` and runs the matching agent inline.

For ordinary chat messages, the system stores the Apple message GUID, sender mapping, timestamp, direction, chat target, and content fingerprint. Raw unrelated conversation is not uploaded to Supabase. Relevant text is retained only for trade evidence, bot questions, answers, or selected recap candidates.

Messages sent by the bot are ignored as inbound triggers when any of these conditions apply:

- the message is from Ben and has a matching outbound reservation;
- the message ends with the bot signature;
- the Apple message GUID was previously reconciled to an outbound record.

If the listener is down, BlueBubbles retries webhooks briefly and then drops them. A script-only cron job every few minutes asks BlueBubbles for messages in allowlisted chats newer than the last recorded GUID and feeds any gap through the same trigger rules, so a listener restart never loses a trade alert.

## Safe iMessage Delivery

Delivery targets are addressed by exact chat GUID and verified participant-set fingerprint, not mutable chat name. Test mode can send only to the self-test chat. Production mode can send only to the approved league chat. The delivery layer in `ultimate_guillotine.messages` is the only code that calls the BlueBubbles send API for league or self-test chats.

Delivery is effectively-once across the external Messages boundary:

1. Insert an `agent_runs` row using a unique idempotency key.
2. Reserve the exact signed outbound content in `outbound_messages`.
3. Recheck the target GUID, participant fingerprint, and agent delivery mode.
4. Send through the BlueBubbles text endpoint addressed by chat GUID. The Private API helper is not required and not installed; plain text to an existing chat uses the standard send method.
5. Record the BlueBubbles message GUID and delivery time, and post the mirror to `#guillotine-feed`.
6. If the process dies after sending but before recording success, the next attempt queries BlueBubbles for recent messages in the same chat with the same content hash before retrying.

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
- answer a tagged question using retrieved league sources;
- draft anything for a future fun agent, subject to the same validate-then-send step.

AI may not:

- choose the weekly low score or rank teams;
- decide gulag entry, elimination, or cuts;
- silently resolve ambiguous trade terms;
- modify source facts, rules, rosters, or scores;
- expose private contacts, dues notes, secrets, or unrelated chat;
- call the BlueBubbles send API, directly or through a Hermes platform adapter.

All prompts and model settings are versioned in the repository. Agent runs record the prompt version and source-event IDs used, whether the model ran inside a repository CLI or inside a Hermes agent-mode job.

## Scheduling and Time

All stored times use UTC. Rule deadlines display in `America/Chicago`, matching the rule document. Mac operations and direct commissioner alerts may additionally show `America/Los_Angeles`.

Event-driven work runs from the webhook listener. Scheduled work runs from Hermes cron on the `guillotine` profile. Game-window jobs such as Game Pulse are scheduled generously and exit early when Sleeper has not yet produced a materially newer snapshot, rather than assuming a fixed game end time.

## Observability and Failure Handling

- The webhook listener and each cron run write a heartbeat or run record to Supabase.
- A script-only health job runs every few minutes and reports stale heartbeats, missed scheduled runs, repeated model failures, BlueBubbles unreachable, and Messages permission failures to `#guillotine-ops`, escalating to `#guillotine-alerts` when a human is needed.
- Operational alerts go to Discord and, when Discord is unreachable, to the self-test iMessage chat. They never go to the league chat.
- Hermes retains cron run history and exposes it with `hermes cron runs` and `/cron list`; Supabase `agent_runs` remains the durable record.
- Jobs use bounded exponential retry inside the CLI. Permanent validation errors enter a failed state with actionable context.
- League-facing agents omit unavailable sections rather than inventing data.
- Supabase and BlueBubbles outages preserve pending work for replay through idempotent re-runs.

## Rollout Gates

Gate 0 applies to the platform before any agent:

1. BlueBubbles Server installed, permissions granted, webhook reaching the listener, and a signed message delivered to the self-test chat by the delivery layer.
2. The `guillotine` Hermes profile created by the install script, connected to its own Discord bot, posting a script-only cron result to `#guillotine-ops`.
3. A forced listener restart between send and record, followed by a reconciliation that creates no duplicate.

Each agent then progresses independently:

1. Fixture tests with recorded, anonymized inputs.
2. Dry run with persisted output and no send, visible in `#guillotine-drafts`.
3. End-to-end delivery to the self-test chat.
4. At least one successful replay/duplicate test.
5. Production mode enabled explicitly for that agent.

The first production agent will be Trade Registrar because its trigger is narrow and its output is easy to audit. Weekly Adjudicator follows after deterministic historical replay. Narrative and interactive agents follow after the shared factual layer is stable.

## Out of Scope

- Modifying Sleeper rosters or scores through automation.
- Sending from a separate Apple identity.
- Running an authoritative local database.
- A league-member Discord server or any non-iMessage league surface.
- Enabling Hermes's BlueBubbles adapter or any Hermes platform that can reach the league chat.
- The BlueBubbles Private API helper, which requires disabling System Integrity Protection.
- Automatically changing league rules from chat discussion.
- Guaranteeing a projection percentage when projection coverage is below the approved threshold.
