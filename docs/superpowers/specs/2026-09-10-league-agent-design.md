# League Agent

## Purpose

One `@bot` in the league chat, one agent behind it. The League Agent answers anything a member
asks about the league — a FAAB balance, a rules question, who holds a player, who won in 2022,
"what team could realistically hold Brock Bowers for me this week and for how much FAAB while he's
injured" — by reasoning over live league data and cited NFL research, not by matching the question
to a hard-coded pipeline. It decides for itself whether a question is a five-second lookup or a
twenty-minute research job, and it says so in the chat while it works.

The agent is a Hermes agent session with read-only tools. The repository owns everything around
the session: the trigger, who is asking, the tools the session may call, the contract its answer
must meet, the fact-checking of that answer, the file it sends, and the record it leaves. The
model creates; the code checks facts and delivers. That is the foundation's create → validate →
send pattern (`docs/superpowers/specs/2026-08-27-automation-foundation-design.md`, "Create,
validate, send"), with the "create" step now an agent rather than a single call.

### Supersedes

This design replaces two earlier ones, and both should be read as history:

- `docs/superpowers/specs/2026-08-27-league-concierge-agent-design.md` — the same "one `@bot`"
  idea, built as one structured call choosing one tool from a fixed table. The constrained-tool
  idea survives here as the MCP server; the classifier-and-dispatcher does not.
- `docs/superpowers/specs/2026-09-09-trade-advisor-design.md` — a deterministic
  score-and-enumerate pipeline around one tool-less model call. It answered exactly the questions
  its phrase list anticipated and none of the ones the league actually asks. Its plumbing —
  the league snapshot, price history, run records, delivery, the dry-run command, the fixture
  league, the golden-set test shape — is kept and reused; its analysis is deleted.

Ben's rulings that shaped this, recorded so the reasoning is not lost: the rulebook is a floor
for creativity, not a ceiling ("last year there was even a gulag insurance deal"); web research
is allowed for everyone, so fairness holds; the agent takes as long as it needs, with a progress
note after five minutes; replies are public in the chat; follow-ups are real iMessage replies to
the bot's message; the deep answer travels as an HTML file, not a web page; and the record of
every question and answer is kept privately. The old Advisor rule against naming another team's
pressure is dropped — the board already ranks every team by projection, and this is a fantasy
league.

## Trigger

Two deterministic gates in the listener, ahead of any model, and nothing else:

1. **Allowlisted chat.** The message's chat GUID matches the registered self-test delivery
   target (`private.delivery_targets`, mode `test`), resolved exactly as
   `advisor_chat_guid` resolves it today. Promotion to the league chat is a deliberate code
   change in that resolver, reviewed with Ben — not a row and not a flag.
2. **Addressed to the bot.** Either the message carries the Concierge tag (`@bot`,
   `@guillotinebot`, case-insensitive, anywhere in the text) **or** it is an inline reply to one
   of the bot's own messages (see "Follow-ups"). The bot's own posts are excluded by their
   signature, as every trigger already excludes them.

There is no intent classifier and no phrase list. A tagged lookup, a tagged rules question and a
tagged strategy question all go to the same agent.

One deterministic safety check is kept from the Advisor, because it costs nothing and needs no
judgement: a message that explicitly tries to overrule the bot — `ignore your rules`, `disregard
the instructions`, `system prompt` and the like, the `_OVERRIDE` half of the Advisor's
`INJECTION` regex — is answered from one fixed refusal line and never starts a session. The
Advisor's other half, refusing imperatives like `register this trade`, is dropped: the agent has no
write path, and explaining that a trade is announced with a 🚨 is a better answer than a refusal.

## Who Is Asking

Unchanged from the Advisor. The listener hashes the sender's handle with
`ultimate_guillotine.data.repositories.handle_hash` and looks it up in
`private.member_contacts` through `MemberContactRepository.member_for_handle_hash`. The agent
is told the asker's **public label only** — `coalesce(nickname, sleeper_display_name,
display_name)`, the string the board renders — never the handle, the hash, or the join key.

A sender the league cannot place is not guessed at. The turn envelope says `sender: unknown` and
the agent's instructions tell it to ask which team to plan for and to plan for nobody until told.
Because follow-ups resume the same session, the member's reply naming their team carries the
conversation on. The commissioner resolves to his own team like anyone else.

## Flow

```text
webhook ──lock──▶ gates ▶ reserve run ▶ immediate kitten receipt ▶ enqueue job ▶ release lock
                                     │
      worker thread (serial) ◀───────┘
        ├─ 5 min           → progress line, then one every 10 min
        ├─ hermes chat (resume for a follow-up) ──▶ LeagueAnswer JSON
        ├─ verify chat text + report ──✗──▶ resume once with the problem ──✗──▶ one-liner
        ├─ render artifact, record private.agent_answers
        ├─ deliver chat text, then the .html attachment
        └─ finish run, store session
```

The listener's work is milliseconds: it never loads league data and never calls a model. The
Registrar's alerts do not wait on research.

## The Agent

### Its own Hermes profile

A second Hermes profile, `guillotine-league`, versioned in `hermes/guillotine-league/` exactly as
the existing `guillotine` profile is versioned in `hermes/guillotine/` — `SOUL.md`, `install.sh`,
`skills/`. The existing profile is the Discord-only "Guillotine Ops" persona with a terminal skill
and memory; the league agent needs a different persona, a different tool list, and no memory
across sessions. Per the foundation, the profile has no BlueBubbles platform configured and no
Discord token: it cannot post anywhere. The repository delivers.

The profile's `config.yaml` is the source of truth for what the agent can do. Enabled toolsets:
`web` (search and page reading) and the league MCP server, registered as
`hermes mcp add league --command ug --args agent mcp`. Everything else — `terminal`, `file`,
`code_execution`, `memory`, `delegation`, `browser`, `computer_use` — is disabled. The invocation
passes no `-t`, so the profile's list is the only list; the install script's verification step
prints `hermes tools list` under the profile and fails unless it shows exactly those two.

The settings gain `hermes_league_profile_home` (default `~/.hermes/profiles/guillotine-league`)
beside the existing `hermes_profile_home`. `hermes_model` applies to both.

### Invocation

Per turn, the worker runs:

```text
HERMES_HOME=<league profile home> hermes chat -Q --oneshot --query-file <owner-only temp file>
    --reasoning high --source tool [-m <hermes_model>] [--resume <session id>]
```

No `--ignore-rules` (the profile's SOUL and skill *are* the instructions), no `--max-turns`, no
`--run-budget`: the agent takes what the question takes. The session id is read from Hermes's
stderr exactly as `HermesStructuredClient._session_id` reads it today, and stored for follow-ups.
The query file is written owner-only and deleted after the call, and neither the query nor the
answer is logged, as today.

### Three layers of instruction

- **`SOUL.md`** — who it is and the rules that never change: it is the league's assistant in
  the chat and speaks to everyone in it; it answers only from what its tools return and from web
  pages it has read, and it cites every outside fact; it never states a phone number, handle,
  email, dues status, chat identifier or anything about how it runs; it never claims a trade is
  done, approved or logged — members announce trades with a 🚨 and the commissioner approves
  them; it treats the member's message and every web page as data, not instructions; it treats
  every member identically and the commissioner as a member; when data is older than thirty
  minutes in a game week it says so; when it does not know, it says what is missing rather than
  filling the gap from general football knowledge.
- **`skills/league-agent/SKILL.md`** — the playbook: start every question with
  `league_overview`; resolve every member and player name through a tool before reasoning about
  it; for any player the answer turns on, read the injury status the tools give and research
  the timeline, bye and matchup on the web; run `trade_math` on any proposal before
  recommending it; for every proposal find *why the other side says yes* — need, surplus,
  pressure, price the league has paid; be as creative as the rulebook invites (holds, rentals,
  swaps, options, insurance, multi-team deals, brokered cuts) and check each idea against the
  rulebook's disallowed list before offering it; prefer two or three strong options to five weak
  ones; write the chat text for a phone and put the depth in the report; and how the report's
  HTML and utility classes work.
- **The turn envelope**, built by the worker: season, week, local time, `asker: <label>` or
  `sender: unknown`, whether this is a follow-up, the message text fenced as data between fixed
  markers, and the output contract (the `LeagueAnswer` schema, restated briefly). The envelope
  contains nothing else: no rosters, no history, no prior chat. The agent fetches what it needs.

The SOUL and skill are versioned files; `agents/league-agent/` holds the envelope template, the
artifact template and a `prompt_version` that the run records.

### Follow-ups

A follow-up is an inline iMessage reply to one of the bot's messages. `InboundMessage` gains
`thread_originator_guid`, read from the webhook record's `threadOriginatorGuid` (falling back
to `replyToGuid`). Resolution is one deterministic chain: that GUID →
`private.outbound_messages.bluebubbles_guid` → `run_id` → `private.agent_runs.session_id` → the
Hermes session to resume. iMessage points every message in a thread at the thread's root, so a
reply to a reply to the bot's answer, or a reply to its "on it…" line, resolves to the same
session.

A follow-up needs no tag: replying to the bot is the signal. A tagged message that is not a reply
starts a fresh session. Sessions do not expire on a clock; a reply to a week-old answer resumes
it, and the envelope's week and the tools' live reads keep it honest. A session whose Hermes
transcript no longer exists — Hermes reports the resume failure — starts fresh, and the answer
opens with one line saying it lost the thread.

Reading `threadOriginatorGuid` needs nothing from BlueBubbles beyond what the webhook already
delivers. *Sending* inline replies (`selectedMessageGuid`) needs the Private API, which the
runbook keeps off; if it is ever turned on, posting the answer as a reply to the question is a
one-field change in `send_text`, noted here and not built.

## The League MCP Server

`ug agent mcp` runs a stdio MCP server (Python `mcp` SDK) that Hermes launches as a subprocess.
It is the privacy boundary now: every result is built field by field from public league values,
never by serializing a row. Every tool is read-only, deterministic, and answers the same for every
asker. Every result carries `as_of`, the sync time of what it read, so the agent can report age.

Names resolve **in the tools**, never in the model: a member token is matched against
`public.members.display_name`, the nicknames in `private.member_aliases` and the active season's
team names through `MemberAliasRepository`; a player token against `public.players.full_name` and
the current rosters. Exactly one match resolves. Zero matches returns an error naming the token;
two or more returns an error listing the candidate labels — the agent relays either as a
clarification rather than guessing. Results name members by their public label only.

| Tool | Parameters | Returns |
| --- | --- | --- |
| `league_overview` | — | season, week, season type, sync ages; every team: label, team name, FAAB remaining, eliminated (and which week), this week's projected total and coverage flag, position on the board (projected rank, lowest first — the guillotine's order); the week's gulag/elimination state |
| `roster` | `member`, `weeks` (default: current week) | holdings with position, NFL team, lineup slot, injury status, projected points per requested week; IR and taxi marked |
| `player` | `name` | who holds them (or free agent), position, NFL team, injury status, projections; ambiguous names listed |
| `projections` | `members[]` (empty = all), `week`, `scope` (`starters` \| `roster`) | side-by-side projected points, or the leaderboard |
| `trades` | `season` (default current), `member` (optional), `limit` | registered trades, current revision, terms only: code, week, parties, assets, conditions; never `evidence_excerpt` |
| `price_history` | `position`, `kind` (`permanent` \| `rental` \| `all`) | comparables and the median FAAB the league has paid, from `advisor/pricing.py` |
| `trade_math` | `legs[]` (`kind`: `player` \| `faab`, `player`, `from`, `to`, `amount`), `weeks` | per side: change in best legal starting lineup over the weeks, FAAB after, and feasibility flags — player not on the sending roster, FAAB over budget, party eliminated; per player: points above the league's replacement level |
| `rules` | `topic` (optional) | the curated `agents/trade-registrar/league-rules.md`, whole or the section matching the topic |
| `history` | `season` (optional) | placings from `public.season_results`, team count, and that season's catalogued trades from `public.trade_catalog` |
| `survival` | `week` (default current) | that week's scores from `public.weekly_results`, who entered the gulag and who was cut, and the latest `public.survival_snapshots` summary when one exists |

`trade_math` is where the Advisor's arithmetic earns its keep: the lineup-delta and
replacement-level functions from `advisor/candidates.py` and `advisor/scoring.py` move under the
tools unchanged. Nothing else of the candidate generator survives — the agent proposes, the tool
prices and checks.

Under `UG_AGENT_FIXTURE=1` the server answers from `advisor/fixture.py`'s closed-form league
instead of the database, which is how the golden set runs a real Hermes session against nothing
real.

## The Answer Contract

The agent's final response contains one fenced JSON object, `LeagueAnswer`, extracted with the
existing `ultimate_guillotine.ai.structured.parse_model_text` and validated as a pydantic model:

- `kind` — `answer` | `clarification` | `refusal`
- `chat_text` — what the chat sees: plain text, no markdown, at most 1,200 characters. For a
  research answer: a headline, one line per option (counterparty, offer, the one-line why), and
  "full write-up attached". For a lookup: the answer.
- `report` — `null`, or `{title, html_body, sources[]}`: the write-up as HTML body markup,
  and the sources it cites as `{url, claim}`. The agent sends a report when the answer is more
  than a few lines; a lookup or a clarification sends none.
- `facts` — the checkable claims behind both texts: `players[]` (`player_id`, `name`,
  `holder` label or `free agent`), `faab[]` (`member`, `amount`), `proposals[]`
  (`counterparties[]`, `legs[]` typed `player` | `faab` | `draft_dollars` | `term`, each with
  `from`/`to` and either a player id, an integer amount, or free text for a `term` such as an
  option, an insurance clause, or "returns before the Week 11 lock")
- `source_line` — one line, e.g. `Source: rosters as of 7:42pm + ESPN injury report`

A `clarification` (which team are you? which Max?) and a `refusal` (private data, favouritism)
carry `chat_text` only.

## Verification

Verification is fact-checking, not list-matching. After the session returns, the worker loads a
fresh `LeagueSnapshot` and checks:

1. every `facts.players[]` entry is where the answer says — on that member's roster, or on no
   roster for `free agent`;
2. every `facts.faab[]` amount fits: an offered amount is at most the named member's remaining
   FAAB; a quoted balance equals the snapshot's;
3. no proposal names an eliminated team as a counterparty;
4. every `report.sources[]` URL is `https`, and every link in `html_body` points at one of
   them;
5. the privacy scan passes over `chat_text` and the report's text content: no phone-number,
   email or chat-GUID pattern, no `dues`, no sender handle, no member `display_name` join key
   that differs from the public label;
6. the size caps hold: 1,200 characters of chat text, 200 KB of rendered artifact.

Nothing about *structure* is checked. A gulag-insurance clause, an option, a three-team hold are
all fine if their facts are true and they are stated concretely enough to announce with a 🚨.
Legality against the rulebook's disallowed list — a no-gain trade to hurt someone, a discount
rental when better offers exist, anything real-life, a survival-odds bet — is the agent's own
last step in the skill's playbook: reasoning, not regex.

**A failed check goes back into the session, once.** The worker resumes the same session with an
envelope naming the problem — `Tony Pollard is on Max's roster, not Joel's; correct the facts
and resend` — and re-verifies. Context is intact, so the correction is cheap. A second failure
ends the run with one fixed line in the chat and the reason, with ids and amounts, in the ops
channel. This is the only retry.

## The Artifact

The report travels as a self-contained `.html` file attached to a second message under the same
run. Tapping it on an iPhone opens Quick Look, which renders HTML with inline CSS; nothing else
is needed. It is the artifact pattern: the agent writes the document, the package makes it safe.

- **Agent-authored body.** `report.html_body` may use headings, paragraphs, lists, tables,
  emphasis, `<details>`/`<summary>`, blockquotes and links — enough for comparison tables, an
  options list with the pitch for each, and a sources section — plus a documented set of utility
  classes (`card`, `pro`, `con`, `num`, `tag`, `muted`) the skill describes.
- **Package-hardened.** The body is sanitized through an allowlist (`nh3`): those elements and
  `class`/`href` only; no script, style, iframe, image, form, SVG, object or event attribute
  survives; `href` must be an `https` URL in `report.sources[]` or a fragment within the document, and
  every external link gets `rel="noopener noreferrer"`. Then it is wrapped in the versioned template
  `agents/league-agent/artifact.html`: the title, the asker's label and the restated question,
  the week and the source line, inline CSS, no external resource of any kind. The rendered file
  contains no `http` reference outside the cited sources.
- **Named from the title**, slugged, with the week: `bowers-hold-week-6.html`.

The chat text goes first, so a member who never opens the file still has the answer; the file
follows. If the attachment send fails after the text went out, one more line says the write-up
did not attach, and the run is recorded `succeeded` with the failure in its error field.

## Record Keeping

Every answer is kept in `private.agent_answers`, revoked from `anon` and `authenticated` like
the rest of the private schema and readable only through the worker role and the dashboard:

| Column | What |
| --- | --- |
| `run_id`, `session_id` | the run and the Hermes session |
| `chat_guid_hash`, `asker_member_id` | where and who (nullable for an unknown sender) |
| `question` | the member's message, verbatim — private, as `source_messages.excerpt` already is |
| `is_follow_up` | whether the turn resumed a session |
| `kind`, `chat_text`, `source_line` | what the chat saw |
| `report_title`, `report_html` | the artifact exactly as sent, or null |
| `facts`, `sources` | the contract's checkable claims, as jsonb |
| `prompt_version`, `model` | what produced it |
| `created_at` | when |

Nothing from this table reaches the site. The site is unchanged by this design.

## Delivery

`DeliveryService` gains `deliver_attachment(run_id, agent, filename, data)` beside `deliver`. It
follows the same path: reserve an outbound row (content `attachment:<filename>`, content hash over
the bytes) → commit → `sending` → commit → `BlueBubblesClient.send_attachment` →
`sent` with the returned GUID. The BlueBubbles endpoint is `POST /api/v1/message/attachment`,
multipart with `chatGuid`, `tempGuid`, `name` and the `attachment` file; it needs no Private API.
Crash reconciliation for an attachment matches the filename among the bot's recent messages,
which means `_record_to_message` also reads each record's attachment names. The Discord feed
mirrors the chat text and the filename, never the HTML.

The signature is applied to chat text by the delivery layer as today; the attachment carries none.

## The Worker

One daemon thread, started with the listener, with its own psycopg connection and an in-memory
queue. It builds its own repositories and its own `DeliveryService` on that connection; nothing
it does touches the listener's connection or its commit boundaries. Jobs run one at a time, in arrival order; the Mac mini runs one Hermes session at a time
and the chat reads one answer at a time. A question that arrives while another is running waits;
if it waits past twenty seconds it is told "one at a time — yours is next" once.

Per job the worker: starts the pacing timers, five minutes for the first progress line,
then one every ten minutes,
all of them posted only while the job is still running; builds the envelope; runs Hermes;
parses `LeagueAnswer`; verifies, resuming once on failure; renders the artifact; writes
`private.agent_answers`; delivers the chat text and then the file; finishes the run
(`succeeded`, `output_hash` over the chat text, `input_version = <prompt_version>:<model>`);
stores or updates the session row.

The run reservation (`private.agent_runs`, key `agent:<message guid>`) is reserved under the
listener lock before the job is queued, so a redelivered webhook is `skipped` without a session.
The job queue is in-memory on purpose: nothing is retried, so nothing needs to survive a restart
except the record that a question was lost, which the run row already is.

**Hang guard.** A Hermes process that has run for sixty minutes is killed. This is a guard
against a stuck network call, not a budget: the agent's depth is its own business, and the guard
exists so a hung session cannot hold the queue forever.

## Failure Behavior

- **Stale or missing data.** No hard gate. Every tool result carries `as_of`; a table with no
  row for this week says so in the result, and the SOUL tells the agent to report age past
  thirty minutes in a game week and to answer from what it has, or say what is missing. A
  data-layer outage that fails `league_overview` outright yields an honest "the league data
  isn't reachable right now" from the agent, and the worker records the run `succeeded` with
  that answer.
- **Hermes crash, non-zero exit, empty output, or the hang guard.** The chat already heard "on
  it…", so silence is not an option: one fixed line — "Couldn't finish that one — ask me again
  in a bit." — run `failed`, `#guillotine-alerts` notified with the exception class or exit
  code.
- **Answer fails verification twice.** The same line; the reasons go to `#guillotine-ops`.
- **Unknown sender.** The agent asks; the run is `succeeded` with `kind: clarification`.
- **Override attempt.** The listener's fixed refusal; no session, no run beyond the reservation.
- **Listener restart mid-job.** On startup, every `league-agent` run still `running` is
  finished `failed` and, once per chat, the same "couldn't finish" line is posted.
- **Duplicate webhook.** Skipped by the reservation, as today.
- **Attachment fails after the text.** One line saying so; the answer stands.
- **Supabase outage in the listener.** The source message is retained by the processor as
  today; nothing is answered from memory.

## Privacy and Safety

The privacy rules of the foundation and the Concierge hold unchanged, and they are enforced in
three places rather than promised in one: the **envelope** carries the asker's public label, the
message, and the week, and nothing else; the **tools** build every result from public values and
name members by label only; and the **verifier** scans both texts before anything is sent or
recorded. No prompt, envelope, tool result or answer ever contains a handle, a hash, a chat GUID,
a dues value, a phone number, an email, or a `display_name` join key. Ops notes carry statuses,
exception names and verification reasons; the chat sees only fixed lines and verified answers.

The agent has no write tool of any kind. It cannot post — the profile has no messaging platform
and the foundation's AI boundary ("may not call the BlueBubbles send API") stands — and it cannot
touch a roster, a trade, a rule or a score. Prompt injection, from the message or from a web
page, can therefore do two things at most: make the agent say something, which the verifier and
the privacy scan check; or make it fetch a page, which reveals nothing because nothing private is
in its context.

**The AI boundary is amended in one respect**, by Ben's ruling: the agent may read public web
pages for NFL facts — injuries, timelines, byes, matchups, consensus — and must cite each one in
the report's sources. It still may not decide anything the foundation reserves to code.

## Fairness

Every member gets the same SOUL, the same skill, the same tools and the same web. The envelope
names the asker so the agent knows whose roster to plan for; nothing else about the asker reaches
it. There is no per-member memory, no commissioner adjustment, and no record of who has been
friendly to the bot. Pressure — a team's position on the board — is public on the site and may be
said aloud.

## Data Changes

One migration:

- `private.agent_sessions` — `id`, `hermes_session_id text unique`, `chat_guid_hash text`,
  `created_at`, `last_used_at`, `turns int`.
- `private.agent_runs.session_id bigint references private.agent_sessions (id)`, nullable.
- `private.agent_answers` as above, with `run_id references private.agent_runs (id)`.
- An index on `private.outbound_messages (bluebubbles_guid)`, which the follow-up lookup reads
  under the listener lock.
- Grants to the worker role and revocations from `anon`/`authenticated`, following the private
  schema's existing pattern.

`InboundMessage` gains `thread_originator_guid: str | None` and `attachment_names:
tuple[str, ...]`; `parse_webhook` and `messages_after` fill them from the record.

## Settings and Commands

- `hermes_league_profile_home` — the league profile's home.
- `ug agent mcp` — the MCP server; `UG_AGENT_FIXTURE=1` serves the fixture league.
- `ug agent ask --text … --as <member> [--resume <session id>] [--fixture] [--out DIR]` —
  the dry run: runs the whole pipeline with no delivery service, no run repository and no
  database writes; prints the chat text, writes the artifact to `DIR`, and prints the
  verification result and the session id. It cannot post, by construction, exactly as
  `ug advisor ask` could not. `--fixture` starts Hermes with the fixture MCP.
- `ug agent answers [--last N]` — lists recent `private.agent_answers` rows for review from
  the terminal.

## Package Layout

```text
ultimate_guillotine/agent/
  trigger.py        gates, override check, follow-up resolution, listener registration
  envelope.py       the per-turn query and the prompt version
  session.py        HermesAgentClient: run/resume, session id, hang guard
  worker.py         the queue, pacing timers, the job pipeline, startup reconciliation
  answer.py         LeagueAnswer schema and extraction
  verify.py         fact checks, privacy scan, the retry envelope
  artifact.py       sanitizer + template rendering
  records.py        AgentSessionRepository, AgentAnswerRepository
  tools/
    mcp.py          the server and tool registrations
    names.py        member and player resolution
    snapshot.py     (moved from advisor/state.py)
    pricing.py      (moved from advisor/pricing.py)
    math.py         lineup delta and replacement levels (from advisor/candidates.py, scoring.py)
    fixture.py      (moved from advisor/fixture.py)
agents/league-agent/
  envelope.md       the turn template, with prompt_version
  artifact.html     the artifact template
hermes/guillotine-league/
  SOUL.md, install.sh, skills/league-agent/SKILL.md
```

`trades/context.py` keeps importing the snapshot from its new home. The listener registers the
agent's trigger where it registers the Advisor's today, and the Advisor's registration goes.

## Testing

Offline by default, as the whole suite is today.

- **Gates and plumbing.** Tag and reply detection; the override refusal; sender mapping;
  follow-up resolution through thread GUID → outbound → run → session, including a reply to a
  reply and a reply to the "on it…" line; a tagged non-reply starting fresh; the envelope
  containing the label, the week, the fenced message and nothing else — asserted by scanning
  it for a handle, a hash, a GUID, a dues value and a join key; the worker's pacing timers and
  the hang guard against a fake Hermes that sleeps; startup reconciliation; attachment
  delivery's reserve → commit → send → reconcile-by-filename with a crash injected after the
  send.
- **MCP tools.** Every tool over the fixture league: one, ambiguous and zero name matches;
  `as_of` on every result; injury status surfaced; `trade_math` feasibility flags; and a scan
  of every result for join keys, handles and hashes.
- **Artifact hardening.** The sanitizer drops script, style, iframe, image, form, SVG and event
  attributes; keeps the allowlisted elements and classes; rejects an `href` outside the sources;
  the rendered file has no external reference; the size cap.
- **Verification.** A player on the wrong roster, a quoted FAAB that does not match, an offer
  over budget, an eliminated counterparty, an unsourced link, a privacy-scan hit — each fails,
  the retry envelope names the problem, a second failure yields the fixed line and an ops note
  with the reason.
- **Golden set.** A fake agent by default — a stub Hermes runner returning canned `LeagueAnswer`
  JSON per question — and the real one with `UG_LIVE_AI_TESTS=1`, always against the fixture
  league through `UG_AGENT_FIXTURE=1`. Questions: the eleven kinds of the Advisor's golden
  set (a positional rental, moving one of three receivers, a named counterparty, a team near
  the cut line, nothing sensible on the board, an unknown sender, stale data, below-coverage
  projections, an override attempt, an order to execute a trade, a request for private data)
  plus a player-anchored hold ask (the Bowers question), a FAAB lookup, a rules question, a
  history question, a follow-up reply, and a general NFL question. The stale and
  below-coverage cases no longer assert a refusal: they assert that the tool results carry the
  age and the withheld projection, and that the answer still goes out. Asserted: the outcome, exactly the expected messages
  delivered, the run's `input_version`, the artifact's validity, and the privacy invariants —
  never the prose. A live answer may decline; it may not fail verification.

## Rollout

1. The golden set green; `ug agent ask --fixture` answers with the fake agent.
2. Mac-mini setup, as a runbook section: install the `guillotine-league` profile, register the
   league MCP, verify the tool list.
3. A week of `ug agent ask` dry runs against the real league with Ben's own questions; artifacts
   opened on his phone.
4. Live in the self-test chat only, the Advisor's trigger removed in the same change.
5. Promotion to the league chat: a deliberate edit to the chat resolver after a week of
   self-test output Ben has signed off on. Criteria: zero private data in any envelope, tool
   result, answer or artifact across the golden set and the self-test week; every answer either
   verified or honestly declined; artifacts opening cleanly on iPhone; follow-ups resuming the
   right session every time.

## Removed

- `advisor/detect.py`, `models.py`, `prompt.py`, `verify.py`, `format.py`, `skill.py`,
  `candidates.py` (except the arithmetic that moves to `agent/tools/math.py`), `scoring.py`
  (likewise), `cli/advisor.py`, `agents/trade-advisor/`, the Advisor's listener registration and
  `advisor_chat_guid`, and their tests. `tests/advisor/fixture.py` moves with the fixture.
- The Trade Advisor and League Concierge specs each get a one-line "superseded by" note at the
  top; the runbook's Trade Advisor section is replaced by the League Agent's.

## Out of Scope

- Commissioner actions, Sleeper writes, registering or approving trades. The agent explains the
  🚨 path.
- Private replies to the asker, and inline-reply sending (both noted as later options).
- Any page on the site for answers.
- Unsolicited posts: the agent never speaks unless addressed.
- Answering in any chat but the registered ones.

## Open Items for Ben

1. **The web toolset's search backend.** Web search inside Hermes uses whichever search
   backend the profile configures; the install step will surface what the league profile needs
   (an API key for the search provider, if any). Nothing in this design depends on which one.
2. **Reviewing answers.** `ug agent answers` lists them in the terminal; if a Discord mirror of
   the artifact (as a file in `#guillotine-feed`) would be more useful than the filename alone,
   it is a small addition to the feed hook.
