# Trade Registrar Agent

## Purpose

Detect official trade announcements in the allowlisted league iMessage chat, convert them into structured trade and contract records, prevent duplicate logging, and automatically post a signed confirmation or clarification request.

This agent uses the shared design in `docs/superpowers/specs/2026-08-27-automation-foundation-design.md`.

## Trigger

A message becomes a trade candidate only when it contains:

1. the red alert emoji `🚨`; and
2. trade language or recognizable transaction terms such as sends, receives, trades, buys, sells, rents, swaps, FAAB, option, protection, or named player movement.

The BlueBubbles webhook listener on the Mac mini applies this rule deterministically and runs the agent inline, so candidates are normally processed within a few seconds. A gap-fill cron job on the `guillotine` Hermes profile re-reads allowlisted chats after any listener downtime and feeds missed messages through the same rule. Messages outside the production league chat cannot create production trades.

## Extraction Contract

The agent extracts:

- participating league members;
- players, defenses, roster rights, or other fantasy assets;
- FAAB or draft-dollar amounts;
- cash terms when explicitly stated;
- rental start and return conditions;
- gulag protection, no-retrade, keeper, option, substitution, or insurance terms;
- effective season and week;
- source message GUID and exact evidence excerpt.

Member aliases and player names are resolved against the active season, Sleeper roster data, player directory, and private alias mappings. The structured proposal must validate before it becomes an accepted trade.

## Validation

Validation requires at least two recognized parties and one explicit asset or obligation. Amounts must retain their unit. A rental must preserve its return condition if one was stated. The agent may represent unusual terms verbatim in a structured `special_terms` field but may not reinterpret them.

If required meaning is ambiguous, the agent posts a concise clarification request in the league chat. It does not log a final trade or guess the missing term. The clarified response must reference or unmistakably identify the candidate before processing resumes.

## Deduplication and Revisions

Deduplication uses three independent unique identities:

- Apple message GUID for source-level replay protection;
- normalized message fingerprint for copied/reposted alerts;
- semantic trade fingerprint over season, parties, normalized assets, amounts, rental conditions, and effective week.

An exact semantic match is a duplicate and receives no second confirmation. A materially different alert involving the same trade context creates a new immutable `trade_revisions` row and updates the current `trades` projection. The agent posts `Trade updated` with the changed terms.

A rescinded trade creates a compensating league event and preserves the original record. Rescission requires an explicit red-alert announcement or commissioner command; casual discussion does not remove a trade.

## Output

Accepted confirmations use a compact format:

```text
🚨 Trade T-2026-014 logged
Max receives: Ja'Marr Chase
Evan receives: DJ Moore + 450 FAAB
Week 2 · Permanent
— 🤖 Guillotine Bot
```

Complex rentals and contracts include the shortest complete summary plus a trade ID that the Concierge can expand later.

## Data Effects

An accepted trade atomically creates or updates:

- source-message evidence;
- immutable trade revision;
- current normalized trade;
- trade assets and obligations;
- public league event;
- agent run and outbound reservation.

Supabase uniqueness constraints, not prompt behavior, enforce idempotency.

## Failure Behavior

- Unavailable AI: leave the candidate queued and alert the commissioner channel after bounded retries.
- Unknown member or player: ask for clarification.
- Supabase unavailable: do not send a confirmation; the gap-fill job replays the message after reconnecting.
- BlueBubbles unavailable after persistence: keep the outbound reservation pending and reconcile against recent sent messages before retrying.
- Duplicate source or trade: mark the run duplicate and send nothing.

## Test and Rollout

Fixtures cover permanent trades, FAAB-only trades, rentals, multi-party trades, options, no-trade payments, duplicate reposts, amended terms, rescissions, and ambiguous alerts. Historical 2025 contract rows provide replay fixtures.

Production activation requires successful self-test delivery, a forced listener restart between send and receipt recording, a replayed webhook and a gap-fill pass that each create no duplicate trade or message, and the confirmation mirrored to `#guillotine-feed`.

## Out of Scope

- Enforcing whether a trade is fair or collusive.
- Modifying Sleeper rosters.
- Treating non-alert chat discussion as an official trade.

