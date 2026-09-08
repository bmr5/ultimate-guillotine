# Weekly Storyteller Agent

## Purpose

Publish an entertaining, factually grounded weekly league recap after Weekly Adjudicator finalizes the scoring week.

This agent uses the shared design in `docs/superpowers/specs/2026-08-27-automation-foundation-design.md`.

## Trigger

The agent runs once for each newly finalized weekly state, normally Tuesday after Weekly Adjudicator posts final results. A corrected weekly state queues a correction decision, not an unconditional second full recap.

The unique run identity is season, week, finalized state version, recap prompt version, and facts hash.

## Inputs

The narrative model receives a structured fact packet containing:

- final scores and ranks;
- eliminated or cut team;
- current gulag result and new entrants;
- closest escape and largest scoring movement;
- accepted trades, rentals, options, and FAAB obligations from that week;
- survival snapshots from prior game windows;
- league records and historical comparisons supported by normalized history;
- prefiltered chat-highlight candidates with source message IDs;
- next week's rule phase and deadlines.

It does not receive member contacts, dues notes, unrelated chat history, Apple handles, credentials, or unverified claims.

## Content Contract

Each recap includes, when supported by facts:

1. headline and one-sentence week summary;
2. elimination, cut, or gulag result;
3. closest escapes and notable collapses;
4. trades and contract consequences;
5. records or historically notable results;
6. one or more selected chat moments;
7. what changes next week.

The tone may be playful and competitive, but it must not invent quotes, trades, scores, motivations, or personal facts. Direct quotes require an exact retained source excerpt. Unsupported sections are omitted.

## Chat Highlight Selection

A repository CLI prefilters candidates using league relevance signals such as reactions, replies, league keywords, trade alerts, and bot interactions. The model selects only from that candidate set. The chosen source IDs are stored with the recap for audit and correction.

## Factual Validation

Before delivery, deterministic validation checks every named score, rank, member, player, trade ID, amount, and week against the fact packet. Generated copy that introduces an unsupported structured claim is regenerated once; a second failure falls back to a deterministic recap template.

## Output and Corrections

The recap is stored in Supabase before delivery and then sent as one signed message when practical. If Messages length or formatting constraints require parts, each part uses one shared recap ID and ordered part number.

A later stat correction produces a short signed correction when it changes a fact stated in the recap. It does not resend an entire recap unless the elimination outcome changed.

## Failure Behavior

- AI outage: use deterministic structured recap.
- Missing historical data: omit historical comparison.
- Missing chat candidates: omit chat moments.
- Factual validator failure: use deterministic fallback and alert the commissioner channel.
- Messages outage: retain the recap, but do not send it after the next scoring week has begun without a commissioner override.

## Test and Rollout

Fixtures cover a normal gulag week, week-one no elimination, week-12 double elimination, direct-cut week, no trades, multiple complex contracts, no chat highlights, historical record, unsupported model claim, duplicate run, and corrected final score.

Tone tests run through the self-test chat. Production begins after factual replay of at least two historical weeks and one current shadow week.

## Out of Scope

- Deciding official results.
- Publishing unrelated private chat.
- Generating fake quotations for humor.

