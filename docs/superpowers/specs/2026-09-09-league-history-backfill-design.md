# League History Backfill

## Purpose

Load past-season trades into Supabase once, as real league history, so the Trade Advisor and
the League Concierge reason about how this league actually trades rather than about one
season's rows. Two sources carry that history: the commissioner's contracts spreadsheet, and
the league iMessage chat's own archive, which reaches back to 2020 and holds roughly 409
messages shaped like trade alerts — about 238 in the 2025 season, 74 in 2024, 70 in 2023.

This is a one-time operator task, not an agent. It uses the shared design in
`docs/superpowers/specs/2026-08-27-automation-foundation-design.md` and the pipeline specified
in `docs/superpowers/specs/2026-08-27-trade-registrar-agent-design.md`. It sends nothing and
never writes the current season.

## Inputs

1. `history/contracts/2025-26/all-contracts.xlsx` — sheet 1, header `Date, Week, Terms,
   Parties…`, already parsed by `load_replay_rows`. Hand-maintained, 2025 only, no message
   provenance.
2. The league chat archive, read through the BlueBubbles REST API on the Mac mini with
   `BlueBubblesClient.messages_after(chat_guid, after, limit)`, paging forward from the start
   of each target season. This is the same chat GUID that is the production delivery target,
   read GET-only.

## Seasons

The proposal is to load **2025 fully** from both sources and treat **2023 and 2024** as a
stretch loaded from the chat alone, since no spreadsheet exists for them. 2022 and earlier
hold a handful of alerts and predate the current rules version. The final choice is an open
question below; the command takes one `--season` at a time, so it can be made per season.

**Season rows.** Each past season needs a `public.seasons` row first — every trade hangs off
`season_id`, and `TradeRepository.accept` raises `LookupError` without one. Its
`sleeper_league_id` comes from walking backwards from the live league: `get_league` returns
`previous_league_id` for each season's league, so 2026 → 2025 → 2024 → 2023. `SleeperLeague`
declares only `league_id`, `name`, `season`, `total_rosters` with `extra="ignore"`, so it
needs a `previous_league_id: str | None` field. The walk is verified, not trusted: a
discovered league must report `season` equal to the year being loaded and `total_rosters`
equal to that season's `expected_rosters` before a row is inserted. `rules_version` is
recorded as `historical-<year>`, because the current rules document does not describe it.

**Members and teams.** For each past league id, `get_users` and `get_rosters` give that
season's humans. Each Sleeper user maps to `public.members` by `sleeper_user_id` where a team
row exists, otherwise by exact Sleeper username against `members.display_name`; a member who
has since left gets a new `public.members` row, because a trade with an unresolvable party is
worse than a member row nobody plays against any more. Each user then gets one
`public.teams` row for that season with `season_id`, `member_id`, `sleeper_user_id`,
`sleeper_roster_id`, `team_name`; the table's `unique (season_id, sleeper_roster_id)` and
`unique (season_id, member_id)` constraints make this rerunnable.

Aliases are not per-season — `private.member_aliases` keys on `member_id` alone — so nicknames
already loaded apply to past-season alerts unchanged, and an alias added to resolve a 2023
alert stays in effect for 2026. That is correct, and it is why the review loop below is an
alias-editing loop.

## Extraction Pipeline

The chat path is the Registrar's pipeline with the clock moved:

1. **Detect.** `is_trade_candidate` — the `🚨` emoji plus trade language — applied unchanged.
   Every other message is counted and discarded in memory. This is what keeps 69,000 messages
   of chatter out of Supabase.
2. **Extract.** One Hermes structured-output call per candidate through
   `StructuredOutputClient.parse`, same prompt version as the Registrar, with that season's
   member list. `not_a_trade` ends the row silently.
3. **Resolve.** `resolve_extracted` against `public.players` and a `RosterIndex` built by
   `build_roster_index` from the **historical** league id and historical season year.
4. **Validate and accept.** `validate`, then `TradeRepository.accept`, which allocates the
   code and writes the revision and league event in one transaction.

**Weaker roster evidence, and the fallback.** Sleeper keeps a past league's rosters as
end-of-season state, not state at the moment of a trade: a player acquired in week 3 and cut
in week 9 is on nobody's final roster, so the evidence `resolve_member` uses to separate two
members with the same first name is often silent for history. The rule is unchanged — an
unsettled name is never guessed — but the fallback order for a past season is:

1. Roster evidence from the historical rosters, as today.
2. For a chat row that also exists in the spreadsheet (matched by the context key below), the
   sheet's `Parties…` columns: if exactly one candidate's display name or alias appears in
   that row's party list, that candidate wins.
3. Otherwise the row is not accepted; it goes to the review file as `ambiguous-member` with
   the offending token and the candidate display names, for Ben to fix with an alias.

Player names resolve exactly as they do live. Players who retired before the current directory
was synced will not resolve; those rows land in the review file as `unknown-player`, and are
the main reason a stretch season is a stretch.

## Deduplication Between the Two Sources

Most 2025 trades exist twice — once as a chat alert, once as a spreadsheet row. Two keys
already in the schema settle it:

- The **semantic fingerprint** (`trade_fingerprint`: season, week, kind, party ids, normalized
  assets, amounts, return condition, special terms) is uniquely indexed on
  `public.trade_revisions`, so an identical second reading returns `duplicate`.
- The **context key** (`trade_context_key`: season, sorted party ids, sorted player ids)
  matches a differently-worded reading to the trade it amends. Its `REVISE_WINDOW_HOURS`
  window is wrong here, where both readings are written seconds apart under back-dated clocks;
  the backfill passes the season's whole span as the window instead.

**Authority — this proposes the opposite of the obvious rule.** The chat is authoritative for
timing *and* for the revision chain; the spreadsheet is authoritative only for the final terms
projection. The reason is provenance: a chat alert is the primary artifact, with a real Apple
GUID, a real timestamp, a verbatim excerpt, and its own later amendments, which the Registrar
already turns into a correct revision chain. The spreadsheet is a hand transcription with no
timestamp beyond a date column, no sender, and no record of what was corrected; letting it win
terms wholesale would let a typo in a ledger cell overwrite what the league announced.

So chat rows load first, chronologically, and build the trade and its revisions. A spreadsheet
row that matches an existing trade by context key and whose terms differ materially is then
appended as one further revision, carrying `"source": "contracts-xlsx"` in its terms and a null
`source_message_guid` — the final projection matches Ben's ledger, the chat history stays
intact, and the disagreement shows up in the dedupe report instead of being silently resolved.
A spreadsheet row matching nothing becomes a trade of its own, marked the same way. The pure
alternative (xlsx wins terms outright) is an open question.

## Codes, Events, and Evidence

- Codes are `T-<season>-NNN`, chronological within the season. `accept` allocates from a
  per-season, per-prefix count, so chronological order is a property of insertion order: every
  candidate is sorted by `sent_at` ascending (spreadsheet-only rows by `Date`, falling back to
  `Week`) before the first accept. The `T` prefix is forced regardless of `DELIVERY_MODE`,
  since `code_prefix_for` returns `TEST` in test mode and history must not be numbered as gate
  traffic.
- `public.league_events` gets one `trade` row per accepted trade, keyed
  `trade:<code>:<fingerprint>`. `_accept` writes `occurred_at = now()` today; the backfill
  needs the message's real `sent_at`, so `accept` takes an optional occurrence time. A dated
  event is the point — "who traded with whom, and when" is what the Advisor asks of history.
- `public.trade_revisions.source_message_guid` carries the **real Apple message GUID** for
  every chat-sourced revision, so any trade can be traced to the message that announced it.
  Spreadsheet-only revisions carry `xlsx:<season>:row-<n>`, deliberately not GUID-shaped.
- `private.source_messages` gets one row per accepted candidate: `source_guid`,
  `chat_guid_hash`, `direction` `inbound`, the real `sent_at`, `content_fingerprint`, an
  excerpt truncated to the existing 2000-character limit, and `trigger_name`
  `trade-alert-backfill`. `sender_hash` is null — parties come from the text, and the backfill
  has no reason to retain who typed it.

## What Is Not Copied

- No message body beyond the 2000-character excerpt of an accepted alert.
- Nothing at all from a message that fails `is_trade_candidate`: non-alert chatter is never
  written, hashed, counted per sender, or summarized.
- No handles, phone numbers, email addresses, Messages display names, group name, attachments,
  reactions, read state, or tapbacks.
- No chat GUID in cleartext, in Supabase or in the review file — only `chat_guid_hash`.
- No dues or contact data, and nothing about the league's humans beyond Sleeper-public users
  and rosters.

## Operator Workflow

```
ug trades backfill --season 2025 --source chat|xlsx|both [--dry-run] [--limit N]
```

1. `--dry-run --source both` resolves everything and writes nothing. It prints the same
   per-row outcome vocabulary as `ug trades replay` (`created`, `duplicate`, `revised`,
   `clarification: <reason>`, `not-a-trade`, `not-a-candidate`, `failed`, `skipped`) plus a
   summary line, and writes a **review file** to `data/private/backfill/<season>-review.tsv`
   (that tree is gitignored). One line per unresolved row: pass number, source, row or message
   ordinal, outcome code (`ambiguous-member`, `unknown-player`, `unclear`, `invalid`), the
   offending token, and the candidate display names. Nothing else is written down.
2. Ben fixes what he can with aliases — edit the members JSON, run `ug members aliases load` —
   and reruns the dry run to watch the review file shrink.
3. Without `--dry-run` the same pass writes. It refuses when `--season` names the current
   `public.seasons` row, and refuses when `DELIVERY_MODE` is `production`, checked off
   settings before a connection is opened. Delivery is a stub that cannot send, as
   `_SilentDelivery` is for replay, so a mis-set mode cannot turn a backfill into a broadcast;
   the notifier is stubbed too, since a past season fails on rows nobody will fix and must not
   page `#guillotine-alerts`.
4. Rerun after each round of alias fixes until the review file is empty, or its remainder is
   rows Ben chooses to leave alone.
5. `--limit N` stops after N candidate rows, for a cheap first look.

## Idempotency

Rerunning is the normal case, and is safe at three layers:

- **Run keys.** Each row reserves `trade:backfill:<season>:<source-guid>` in
  `private.agent_runs`. A row whose prior run finished `succeeded` or `duplicate` is skipped
  with no model call. A row that finished `clarification` or `failed` is re-reserved with a
  per-attempt suffix, the way `ug trades retry` does, so a second pass after an alias fix
  actually reruns it. This is deliberately unlike `ug trades replay`, where a row is `skipped`
  forever once run.
- **Semantic fingerprint.** A row that slips past the run key resolves to the same terms and
  is refused by the unique index as a `duplicate`.
- **Season, member, and team writes** are upserts against existing unique constraints.

An interrupted backfill leaves a consistent prefix and resumes where it stopped. Codes already
allocated are never renumbered, so a resumed run can leave codes slightly out of chronological
order; if that matters, the season is rolled back and reloaded rather than patched.

## The Current-Season Boundary

The backfill never touches 2026. It refuses a `--season` equal to the newest `public.seasons`
row, reads the archive only up to 23:59:59 America/Chicago on the last day of the requested
season, and writes no `public.teams` row for the live season. The two 2026-09 alerts already
in the chat belong to the live Trade Registrar, to be picked up by the listener and the
gap-fill job after production promotion; they must be free to become `T-2026-001` and
`T-2026-002`. A backfill that swallowed them would leave the league's first two real trades
with back-dated events and no confirmation in the chat.

## Privacy and the Read-Only Guarantee

- Every BlueBubbles call is a `GET`: `/api/v1/ping` and `/api/v1/chat/<guid>/message`. It
  never calls `POST /api/v1/message/text` and holds no reference to `DeliveryService`.
- It runs on the Mac mini only, reading the BlueBubbles password and chat GUID from the
  environment `launchd` and the Hermes profile provide. The archive never leaves that machine
  except as the excerpts and hashes described above.
- The league sees nothing: no send, no read receipt, no typing indicator, no reaction.
- Model calls carry the alert text and the season's member display names — the same payload
  the live Registrar sends today, and nothing more.

## Verification

1. **Row counts by season.** `select s.year, count(*) from public.trades t join public.seasons
   s on s.id = t.season_id group by s.year order by s.year`, compared with the candidate count
   the pass reported. Expect materially fewer 2025 trades than its ~238 alerts, because
   reposts, amendments, and rescissions collapse.
2. **Spot-check list.** The pass prints ten evenly spaced accepted trades — code, date, week,
   parties, first line of excerpt — to Ben's terminal, not to Supabase or Discord, for him to
   recognize. He confirms three of them against his memory of the deal; the recorded GUID is
   the tiebreaker if he wants to find the message.
3. **Dedupe report.** For `--source both`: spreadsheet rows matched to a chat trade,
   spreadsheet-only rows, chat trades with no spreadsheet row, and the list of trades where
   the two disagreed on terms. The disagreements are the interesting output.
4. **Boundary check.** The 2026 trade count is unchanged by every backfill run.

## Rollback

The automation worker holds no `DELETE` grant on `public.trades`, `public.trade_revisions`, or
`public.league_events` by design, so nothing in this repository can undo a backfill. Rollback
is Ben in the Supabase dashboard, by season, in this order:

1. `delete from public.league_events where season_id = <id> and event_type in ('trade',
   'trade_rescinded')`
2. `update public.trades set current_revision_id = null where season_id = <id>`
3. `delete from public.trade_revisions where trade_id in (select id from public.trades where
   season_id = <id>)`
4. `delete from public.trades where season_id = <id>`
5. `delete from private.source_messages where trigger_name = 'trade-alert-backfill'`, and
   `delete from private.agent_runs where idempotency_key like 'trade:backfill:<season>:%'`
6. Optionally that season's `public.teams` rows and its `public.seasons` row.

Members created for departed players are left alone; deleting them would break any other
season that referenced them.

## Failure Behavior

- BlueBubbles unreachable or the archive query timing out: the pass stops, reports the last
  message ordinal reached, and resumes there next run.
- Hermes unavailable: the row fails, is recorded `failed`, appears in the review file, and is
  retried by the next pass. No Discord alert.
- A `previous_league_id` walk that cannot be verified: the pass refuses to insert a season row
  and says which check failed. It never guesses a league id.
- Supabase unavailable mid-pass: the transaction rolls back, and the run key is re-reserved as
  a retry on the next pass.

## Out of Scope

- Backfilling weekly scores, eliminations, gulag history, or FAAB. Trades only.
- Backfilling non-trade chat highlights, recaps, or quotes.
- Any write to the 2026 season, and any send to any chat for any reason.
- Reconstructing rosters as they stood mid-season; Sleeper does not expose it, and the
  Advisor's use of history is about deals, not lineups.

## Open Questions for Ben

1. **Which seasons?** 2025 only, or 2025 plus the 2023–2024 stretch? The stretch costs roughly
   145 more model calls and yields more unresolvable rows, since more of those members and
   players are gone. 2022 and earlier are a handful of alerts — worth it?
2. **Dedupe authority.** This proposes chat-wins-timing-and-chain, xlsx-wins-final-terms as an
   appended revision. Would you rather the spreadsheet win outright wherever the two disagree,
   giving one clean row per trade and a shorter history?
3. **Departed members.** Create `public.members` rows for people who have left so their old
   trades resolve, or drop any trade whose party is no longer in the league?
4. **Spreadsheet-only trades.** Should a trade that exists only in the ledger get a real
   `T-2025-NNN` code alongside chat-sourced ones, or a distinguishable prefix so the Advisor
   can weight it differently?
5. **Effective week for ledger rows.** The sheet has a `Week` column and the chat rarely states
   one. Trust the sheet's week for matched trades even when the chat implies another?
6. **Review file retention.** Delete `data/private/backfill/` once the load is verified, or
   keep it as the record of what could not be resolved?
7. **Historical rules version.** `historical-<year>` is a placeholder. Do past seasons have a
   rules document worth naming?
