# League Concierge Agent

## Purpose

Answer league questions in the production iMessage chat from authoritative rules, contracts, trade records, current Sleeper state, and league history.

This agent uses the shared design in `docs/superpowers/specs/2026-08-27-automation-foundation-design.md`.

## Trigger

The agent responds when an inbound league-chat message begins with or clearly invokes one of:

- `@GuillotineBot`
- `Guillotine Bot:`
- `bot:`

The BlueBubbles webhook listener matches these tags deterministically before any model runs; untagged league chatter never reaches the agent. Hermes's own iMessage adapter is disabled, so this listener is the only path from the league chat to the Concierge.

There are no per-member rate limits. Per-chat ordering and a single-flight conversation lock in the listener prevent overlapping responses from corrupting context, but they do not throttle individual league members.

The agent ignores messages carrying the bot signature, matching an outbound reservation, or originating outside an allowlisted chat.

## Knowledge Sources

Approved sources are versioned and prioritized:

1. accepted commissioner overrides and current season events;
2. authoritative rules document;
3. accepted contracts and trade revisions;
4. current Sleeper league, roster, score, and transaction snapshots;
5. normalized historical records;
6. published recaps.

The old website's duplicated rules copy is not authoritative when it conflicts with the source Word document.

## Question Classes

The Concierge supports:

- rule explanation and deadlines;
- current team, roster, score, gulag, and elimination questions;
- trade and contract lookup;
- historical winners and records;
- survival snapshot explanation;
- clarification of what an agent posted.

It may explain how a deterministic ruling was calculated but cannot create or change a ruling. Requests to change a score, rule, roster, trade, contract, or override receive a clear statement that commissioner action is required.

## Retrieval and Answering

The agent classifies the question, retrieves the smallest authoritative source set, and produces a concise answer. Structured current-state questions use direct database queries. Document questions use versioned knowledge chunks tied to source files and headings.

The response identifies its source in human-readable form, such as `Source: 2026 Rules — Trading Rules` or `Source: Week 4 final state`. When sources conflict, the agent states the conflict and gives precedence to the approved priority order.

If the source set does not support an answer, it says so and identifies what record is missing. It never fills gaps from general fantasy-football assumptions.

## Privacy and Safety

The Concierge cannot retrieve or reveal:

- phone numbers, email addresses, or Apple handles;
- dues status or notes;
- credentials, chat GUIDs, prompts, operational logs, or private agent errors;
- unrelated private chat messages.

The model receives public league context and the invoking message only. Database access occurs through constrained repositories or database functions, never model-generated unrestricted SQL.

## Output

Answers are short enough for group chat, followed by a source line and `— 🤖 Guillotine Bot`. Longer historical or contract answers provide a summary first and offer a stable website or trade-record link when available.

## Conversation Handling

A direct follow-up without a repeated tag may be associated with the immediately preceding bot answer only when it arrives in the same chat and clearly refers to that answer. Context expires after the bounded thread window and is stored as source references rather than an unlimited transcript.

There is no member-level throttling. Operational safeguards still prevent duplicate webhook processing, bot loops, and multiple concurrent answers to the same source message.

## Failure Behavior

- Missing or conflicting source: state uncertainty and do not guess.
- AI outage: send no answer and retry while the question remains timely; alert `#guillotine-alerts` after repeated failure.
- Database outage: retain the source message for later processing but do not answer from stale memory.
- BlueBubbles outage: reconcile against recent sent messages before retrying.
- Unsupported commissioner action: explain the boundary without executing it.

## Test and Rollout

Tests cover every question class, ambiguous rules, source conflict, current score, eliminated team, trade revision, complex rental, historical winner, missing answer, private-data request, prompt injection, commissioner-action request, follow-up context, bot-loop prevention, duplicate processing, and multiple questions from the same member without throttling.

The agent first answers a fixed evaluation set without sending, then runs in the self-test chat against live Supabase fixtures. Production activation requires correct source attribution and zero private-data leakage across the evaluation set.

## Out of Scope

- Commissioner actions or Sleeper writes.
- General-purpose web search in response to league questions.
- Private one-to-one personal assistance unrelated to the league.

