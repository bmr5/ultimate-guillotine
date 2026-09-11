# Trade Advisor Skill

> **Superseded** by `docs/superpowers/specs/2026-09-10-league-agent-design.md` on 2026-09-10. Kept for the record; nothing here is built or maintained.

## Purpose

Answer "who should I trade with, and what should I offer" in the league chat with two or three concrete, defensible proposals: a named counterparty, an exact offer, the reasoning, and the risk. The Advisor is grounded in what the league has actually paid for players — this season's registered trades and last season's replayed contracts — plus live rosters, projections, FAAB balances, and guillotine pressure.

The Advisor is a skill of the League Concierge, not a separate agent. It inherits the Concierge's `@bot` trigger, knowledge-source priority, privacy rules, source attribution, follow-up conversation handling, and the `— 🤖 Guillotine Bot` signature applied by the delivery layer. It uses the shared design in `docs/superpowers/specs/2026-08-27-automation-foundation-design.md` and the shared roster, projection, FAAB, and elimination tables defined in `docs/superpowers/specs/2026-09-09-league-data-layer-design.md`, which it does not redefine.

## Trigger

Three deterministic gates, all in the listener, before any model runs.

**1. Concierge tag.** The message must invoke the Concierge (`@bot`, `@guillotinebot`, case-insensitive) exactly as the Concierge spec defines. Untagged chatter never reaches it.

**2. Advice intent.** Inside a tagged message, a keyword and phrase rule over the normalized text routes to the Advisor rather than to general question answering. It matches any of:

- ask-plus-trade language — "who should I trade", "should I trade", "who wants", "trade ideas", "any trade ideas", "trade advice", "help me trade", "make me a trade", "what can I get for", "what would it take to get", "who would give me", "who needs";
- rental language — "rental", "rent a", "rent me", "borrow", "for the next N weeks", "for this week only", "one-week";
- market language — "opportunities to move", "move a WR/RB/TE/QB", "shop", "shopping", "sell high", "buy low", "dump", "offload", "upgrade my", "I have too many", "I need a";
- explicit invocation — "@bot trade advisor", "@bot advisor".

A tagged message matching none of these stays with the Concierge's normal classifier. A message matching both a lookup pattern ("what did Max trade for Chase") and an advice pattern is treated as a lookup: the Advisor never fires when a factual answer was asked for.

**3. Trusted-chat allowlist.** The Advisor responds only when the inbound message's chat GUID matches a row in `private.delivery_targets`. The listener already drops non-allowlisted chats; the Advisor re-checks through `TargetRepository` so the skill is safe wherever it is called from. Until Ben promotes it, only the `test` row — the self-test chat — is registered for this skill, so the Advisor is silent in the league chat. Production is a later step, gated on the promotion criteria below.

Replies are public in the invoking chat for now. Replying privately to the asker, so a proposal is not broadcast to the counterparty, is a documented later option: it needs a `direct` delivery mode, a per-member outbound target resolved from `private.member_contacts`, and Ben's decision on timing. Nothing here assumes public replies stay the default.

## Who Is Asking

The listener stores each source message with `sender_hash`, the SHA-256 digest of the sender's Apple handle (`private.source_messages.sender_hash`); the handle itself is never stored. The Advisor hashes the inbound sender address the same way, looks it up in `private.member_contacts.handle_hash` for a `public.members` row, then joins `public.teams` on the current `public.seasons` row for the asker's `sleeper_roster_id` and team. Aliases from `MemberAliasRepository` resolve any member the asker names in the message into the same identity space the Trade Registrar uses.

If the sender hash matches no contact, the Advisor does not guess and does not scrape a name from the text. It replies once, briefly, that it cannot tell whose roster to plan for and asks the member to name their team; the run outcome is recorded `unknown_asker`. A follow-up in the same chat naming a known member re-enters the normal path. Ben's own identity resolves to the commissioner's team like any other member and gets no special treatment.

## Inputs

All reads go through the shared data layer; the Advisor owns no tables.

- **This season's market** — `public.trades` and `public.trade_revisions` as the Trade Registrar recorded them, current non-rescinded projection, with assets, amounts, and rental conditions.
- **Last season's market** — the 2025 contracts replayed by `ug trades replay` under the 2025 `public.seasons` row, plus any one-time backfill of 2025 chat alerts.
- **Roster holdings** — roster slots, starters, and bench for all 18 teams, keyed to `public.players`.
- **Projections** — the Sleeper projections snapshot for the current and upcoming weeks, normalized to the league's own scoring settings.
- **FAAB** — remaining waiver budget per team. FAAB is the only currency the Advisor proposes.
- **Guillotine pressure** — each team's margin above the cut line and survival standing for the active week, from the shared elimination and survival state.
- **Rules** — the active rules document version, for what a trade may contain.

## Advice Contract

Every successful answer contains two or three proposals. Each carries: a **counterparty** — one named member, or two for a three-way idea, never "someone with RB depth"; an **exact offer** — the specific players moving each way and any FAAB amount in whole units, players and FAAB only, never cash, Venmo, or dues credit even though such trades exist in chat history; **reasoning** — one or two sentences tying the offer to a need, surplus, projection gap, pressure situation, or a comparable price the league already paid; and **risk** — exactly one line naming how it goes wrong for the asker.

### Bounded Creativity

Creative is allowed; invented is not. Rentals are allowed when the return condition is explicit ("through Week 10, returns before Week 11 lock"). Multi-team ideas are allowed, capped at three teams, each leg stated. Conditional structures are allowed only in forms the rules document and past accepted trades already contain. Nothing may violate the rules document — no moves the rules forbid on eliminated or protected assets, nothing past the deadline, nothing needing commissioner approval presented as done. Anything the Advisor cannot confirm is legal is not proposed. A proposal is a suggestion: the parties still announce a real `🚨` trade for the Registrar to log it.

### Fairness

Every member is scored by the same deterministic function — no per-member weighting, no commissioner adjustment, no memory of who has been friendly to the bot. The commissioner's team appears as a counterparty exactly as often as the scoring says. Only Sleeper-visible league data and the league's own recorded trades are used: no outside rankings, news, or web search. No private chat content is an input beyond the invoking message — not prior chatter, not negotiations in progress, not dues.

## Retrieval Pipeline

Deterministic code does the analysis; one model call does the writing.

1. **Parse the ask** deterministically: position(s), direction (acquire or move on), horizon in weeks, any named counterparty.
2. **Score every team** in code: positional need (starter projection shortfall by slot), surplus (bench players above the replacement line), FAAB headroom, and pressure (margin to the cut line this week).
3. **Generate candidates** by crossing the asker's surplus against every other team's need and the reverse, with a projected-points delta for both sides; drop anything the rules forbid or that involves an eliminated team.
4. **Price them** — attach comparable accepted trades from this season and last as what a similar player fetched.
5. **Rank and write** — one `HermesStructuredClient.parse` call receives the top candidates as compact structured facts and returns a validated schema. The model ranks, discards weak candidates, and writes reasoning and risk. It may not introduce a player, member, or amount absent from the candidate set.

The prompt contains member display names, team names, player names, projections, FAAB integers, pressure ranks, and historical trade summaries. It never contains phone numbers, Apple handles, chat GUIDs, message excerpts other than the invoking question, dues state, or any other private schema value.

### Structured Output Schema

The parse call uses schema name `TradeAdviceResponse`, with nested `AdvisedTrade` and `OfferLeg`.

`TradeAdviceResponse` fields:

- `status` — `ok` | `no_good_trades` | `insufficient_data`
- `headline` — one short line stating what the asker wants
- `proposals` — 0 to 3 `AdvisedTrade`
- `note` — optional single caveat line

`AdvisedTrade` fields:

- `rank` — int, 1-based
- `counterparties` — 1 to 2 member display names
- `asker_receives`, `asker_sends` — lists of `OfferLeg`
- `structure` — `permanent` | `rental` | `multi_team`
- `return_condition` — string or null, required when `structure` is `rental`
- `reasoning` — string, max 240 characters
- `risk` — string, max 140 characters, one line
- `comparable_trade_code` — a `T-<season>-NNN` code backing the price, or null

`OfferLeg` fields:

- `kind` — `player` | `faab`
- `player_id`, `player_name` — set for `player`, both null otherwise
- `amount` — int, set for `faab`, null otherwise
- `from_member`, `to_member` — member display names

Post-parse validation is deterministic and rejects the whole response if any player, member, or amount is absent from the candidate set, if a rental lacks a return condition, if a FAAB amount exceeds the sending team's remaining budget, or if `kind` is anything but `player` or `faab`. A rejected response is retried once, then the run ends with the `no_good_trades` message rather than a fabricated proposal.

## Output

Short enough to read on a phone in a group chat: a one-line lead, then numbered proposals of three short lines each (offer, why, risk), then the Concierge's source line. The delivery layer appends the signature; the Advisor never writes it.

```text
RB rental, next 2 weeks — 2 ideas
1) Joel: you send Rome Odunze + 120 FAAB, you get Tony Pollard through Week 11
   Why: Joel is 2nd in WR need and 14th in RB need; Pollard projects +4.1 over your RB2
   Risk: Pollard's bye is Week 12, so the rental ends right when you need him
2) …
Source: registered trades + Week 6 projections
```

A `no_good_trades` result sends one honest line saying nothing beats standing pat, and why. An `insufficient_data` result names the missing record.

## Rate and Cost Limits

One advice run per invoking message and exactly one model call per run. The Concierge's single-flight conversation lock per chat applies: a second advice request in the same chat while one is running is answered after the first completes, never concurrently. Each run takes one cached snapshot of rosters, projections, FAAB, and pressure at the start and reuses it for every candidate, so a run reads the data layer once. Candidate generation is capped before the model call to keep the prompt bounded. There are no per-member limits, consistent with the foundation.

## Privacy and Safety

The Concierge's privacy rules apply unchanged. In addition, the Advisor never reveals or implies dues status, contact details, chat GUIDs, or run internals; never quotes another member's message or an unrelated chat; treats the invoking message as data rather than instructions, so a message asking it to ignore its rules, favor a member, or reveal private data gets the normal refusal and is recorded; does not create, change, or approve a trade, which is the Registrar's `🚨` path and, where required, commissioner action; and names another team's guillotine pressure only in terms already visible on the league board (see Open Questions).

## Failure Behavior

- **Stale data layer** — if the roster, FAAB, or projection snapshot is older than the freshness window in the data layer spec (target: 30 minutes during game weeks), the Advisor reports the snapshot age instead of advising.
- **Projection coverage below gate** — below the 95 percent coverage of rostered unplayed starters that Game Pulse requires, it answers from need and surplus only and says projections were unavailable, or declines if the ask is projection-dependent.
- **Hermes outage** — nothing is sent; the run is recorded `failed`, ops is alerted, and no answer is produced from stale context.
- **Unknown asker** — one clarification asking which team to plan for.
- **Schema validation failure after one retry** — no proposals are sent.
- **Supabase outage** — the source message is retained; no advice from memory.

## Test and Rollout

A fixture league state — 18 teams with deterministic rosters, projections, FAAB, and a known pressure order — backs a golden request set covering a positional rental ask, a "move one of my three WRs" ask, an ask naming a specific counterparty, an ask from a team near the cut line, an ask with no sensible trade available, an unknown sender, a stale snapshot, a below-coverage run, a prompt-injection attempt, a request to execute a trade, and a request for private data. Golden runs assert the deterministic candidate set and schema validity, not exact prose.

Rollout answers the golden set offline first, then runs live in the self-test chat only, with the `test` delivery target as the sole allowlisted chat. Promotion to the league chat requires: zero private-data leakage and zero contact detail in any prompt across the golden set; every proposal referencing only real rostered players and real FAAB balances; no proposal violating the rules document; a commissioner-team appearance rate consistent with the scoring; and Ben's explicit sign-off on a week of self-test output.

## Out of Scope

- Executing, registering, or approving trades; brokering between members (Broker is deferred).
- Any currency other than FAAB, including real money and dues credit.
- Sleeper writes, waiver claims, or lineup changes.
- Outside rankings, injury news feeds, or web search.
- Unsolicited advice: the Advisor never posts without being asked.

## Open Questions for Ben

1. **Private replies.** Should the Advisor move to replying privately to the asker, and when — at production promotion, or after a public trial? Public replies let the counterparty read the pitch before it is made.
2. **Naming counterparty pressure.** May a proposal say out loud that the counterparty is close to elimination and therefore motivated, or should pressure be described only for the asker's own team?
3. **Rental horizon.** How many weeks ahead should rentals be planned by default when the asker does not say — through the next bye, two weeks, or to the trade deadline?
4. **Draft dollars and protection terms.** May proposals include draft-dollar amounts or gulag-protection terms, both of which appear in past contracts, or stay strictly players-plus-FAAB?
5. **History depth.** Is last season plus this season enough price history, or should the 2023–2024 chat alerts be backfilled before the Advisor quotes comparables?
