# League Concierge Agent

## Purpose

Answer league questions in the production iMessage chat from authoritative rules, contracts, trade records, current Sleeper state, and league history.

This agent uses the shared design in `docs/superpowers/specs/2026-08-27-automation-foundation-design.md`.

## Trigger

The agent responds when an inbound league-chat message begins with or clearly invokes one of:

- `@bot` (case-insensitive; the primary form)
- `@guillotinebot` or `@GuillotineBot`

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

Synced current-state facts — roster slots, weekly projections, FAAB balances, and elimination
status — are read from the tables defined in
`docs/superpowers/specs/2026-09-09-league-data-layer-design.md`. That spec owns those tables;
this one only queries them.

The old website's duplicated rules copy is not authoritative when it conflicts with the source Word document.

## Question Classes

The Concierge supports:

- rule explanation and deadlines;
- current team, roster, score, gulag, and elimination questions;
- trade and contract lookup;
- historical winners and records;
- survival snapshot explanation;
- clarification of what an agent posted;
- league data questions, described in their own section below.

It may explain how a deterministic ruling was calculated but cannot create or change a ruling. Requests to change a score, rule, roster, trade, contract, or override receive a clear statement that commissioner action is required.

## Retrieval and Answering

The agent classifies the question, retrieves the smallest authoritative source set, and produces a concise answer. Structured current-state questions use direct database queries. Document questions use versioned knowledge chunks tied to source files and headings.

The response identifies its source in human-readable form, such as `Source: 2026 Rules — Trading Rules` or `Source: Week 4 final state`. When sources conflict, the agent states the conflict and gives precedence to the approved priority order.

If the source set does not support an answer, it says so and identifies what record is missing. It never fills gaps from general fantasy-football assumptions.

## League Data Questions

A large share of what the chat actually asks is arithmetic over current league state:
"Max and Joel's projections compared to mine", "bottom 5 projections right now", "how much
FAAB does Evan have left", "who is closest to getting guillotined", "who has my old tight
end", "who won in 2022", "what does the rule say about rentals". These are answered from the
tables defined in `docs/superpowers/specs/2026-09-09-league-data-layer-design.md`, the trade
records, `history/league/ultimate-guillotine-records.xlsx`, and the rules document — never
from the model's own knowledge of football.

### Constrained query tools

The model never writes SQL and never sees a connection. It chooses one tool from a fixed list
and fills its parameters; a deterministic dispatcher maps the choice to one parameterized
repository method. Every tool is read-only.

| Tool | Parameters | Answers |
| --- | --- | --- |
| `compare_projections` | `member_ids[]`, `week`, `scope` (`starters` \| `roster`) | this week's projected points for named members side by side |
| `projection_leaderboard` | `direction` (`top` \| `bottom`), `n` (1–18), `week`, `scope` | the best or worst N projections at this moment |
| `faab_remaining` | `member_ids[]` (empty means all 18) | FAAB budget left, and spent |
| `elimination_risk` | `n` (1–18), `week` | who is closest to elimination, by current margin and survival snapshot |
| `roster_lookup` | `member_id`, `position`, `slot` (`all` \| `starters` \| `bench`) | who a member is holding |
| `player_holder` | `player_id` | which team holds a named player |
| `standings` | `week` | records and points for the season to date |
| `trade_history` | `member_ids[]`, `season`, `limit` | accepted trades and revisions, current and backfilled seasons |
| `league_record` | `category`, `season` | winners and records from the records workbook |
| `rules_lookup` | `topic` | the versioned rules chunk that covers a topic |

Ranges are enforced by the dispatcher, not by the prompt: `n` is clamped to 1–18, `week` to
the weeks the season actually has, `limit` to a fixed ceiling, and `season` to a season with a
`public.seasons` row. A tool call naming a member, player, or season that does not resolve is
never executed.

### Classification schema

One Hermes structured-output call through `StructuredOutputClient.parse` turns the question
into a `league_data_query` object, validated client-side before anything runs:

- `tool` — one of the names above, or `none` when no tool fits;
- `member_names[]` — the member tokens as typed, in the order asked, including the literal
  `me`/`my`/`mine` when the asker referred to themselves;
- `player_name`, `position`, `slot`, `scope`, `direction`, `category`, `topic` — optional,
  each constrained to its enum or left null;
- `n`, `week`, `season`, `limit` — optional integers;
- `unsupported_reason` — set when `tool` is `none`, saying what the question wanted.

`tool: none` falls through to the existing question classes rather than being answered. A
question that needs two tools ("my projection and my FAAB") is allowed to produce a short
ordered list of at most two calls; anything longer is answered with the first and an offer to
ask again.

### Resolving member names

Member tokens resolve deterministically, never by the model. Each token is normalized and
matched against `public.members.display_name`, the nicknames in `private.member_aliases`, and
the active season's `public.teams.team_name`. Exactly one match resolves. Zero matches
produces a clarification naming the token that was not recognized. Two or more matches
produces a clarification listing the candidate display names, in the same voice the Trade
Registrar uses — `Two members go by 'Max'; which one?` — and nothing is queried until the
chat answers.

`me`, `my`, and `mine` resolve to the sender, from the listener's sender mapping, before the
model is called. A sender whose handle maps to no member is asked who they are rather than
being silently dropped.

### Freshness

Every data answer ends with the age of what it read: `as of <sync time>`, in
`America/Chicago`, taken from the sync timestamp the data layer records for the table that
answered. When the newest sync is older than that table's staleness threshold, the answer says
so plainly and still gives the number. A projection answer during a live game window names the
projection snapshot time, not the request time — the difference is the whole question.

### Trusted chats

The Concierge answers only in chats registered as delivery targets in
`private.delivery_targets`, matched by exact chat GUID and participant fingerprint. The
self-test chat comes first; the production league chat only after that agent is promoted
explicitly. A tagged question from any other chat is recorded and ignored. This is the same
allowlist wording the Trade Advisor uses, and it is enforced in the listener before any model
runs.

### Trade Advisor

The Trade Advisor is a Concierge skill, not a separate agent: it shares this trigger, this
allowlist, this delivery path, and this privacy boundary. It is specified in
`docs/superpowers/specs/2026-09-09-trade-advisor-design.md`.

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
- Model-generated SQL or any unconstrained query path.

## Open Questions for Ben

1. **Which historical records?** `history/league/ultimate-guillotine-records.xlsx` holds past
   winners and records. Load every sheet as queryable rows, or only champions and a short list
   of records worth arguing about in chat?
2. **Does "my" always mean the sender?** Resolving `me` from the sender handle is the obvious
   reading, but a member asking on someone else's behalf, or asking from a second device
   whose handle is not mapped, would be told the bot does not know who they are. Acceptable,
   or should an unmapped sender be asked to name themselves once and be remembered?
3. **Do rules answers quote the document verbatim?** A quoted clause is unambiguous and
   settles arguments; a paraphrase reads better in a group chat. Quote verbatim with the
   heading as the source line, paraphrase with a quote available on request, or both depending
   on length?

