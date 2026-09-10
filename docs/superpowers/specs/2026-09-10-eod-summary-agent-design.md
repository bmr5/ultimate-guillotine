# EOD Summary Agent

## Purpose

Every night, one signed message to the league chat that says where every roster stands and who
is likely to die: the live score and projected finish of all eighteen teams, the two teams
currently on the block (or the gulag pair fighting for their life), a Monte Carlo estimate of
each team's odds of the week's adverse event, the roster problems worth fixing before the next
kickoff, and the day's moves.

Ben's ask (2026-09-10): "an agent that does end of day summaries that share the state of how
every roster is doing in the league and who's likely to die and all that … have it ready so by
the end of week 1 it will work." He was not available to answer questions, so every decision
below was taken to ship a working nightly post by the end of week 1 and is recorded so he can
overrule it.

This agent uses the shared design in
`docs/superpowers/specs/2026-08-27-automation-foundation-design.md` and reads only the tables in
`docs/superpowers/specs/2026-09-09-league-data-layer-design.md` (plus the live scores table and
the transactions log added since). It is the first consumer of the survival model the Game Pulse
spec (`2026-08-27-game-pulse-agent-design.md`) describes; the engine is built here, and a
game-window Game Pulse post is a second schedule of the same command, not a second engine.

## Trigger and Cadence

Two script-only Hermes cron rows under one agent, in the Mac mini's local time (Central):
`guillotine-eod-summary` at `15 8 * * 0,1,3` (8:15 AM Wednesday, Sunday, Monday) and
`guillotine-eod-summary-waivers` at `12 10 * * 4,6` (10:12 AM Thursday and Saturday, after each
waiver round). Ben's cadence (2026-09-10, after the first dry run): "I would take a break on this on Tuesdays. Wed
it could be useful before auctions close. Thursday auctions clear it could be useful after
that, Thursday games happen so it's definitely useful Friday morning. Then a lot of FA happens
Saturday, it could be most useful Sunday morning and Monday morning." The first waiver round
closes Thursday 2 AM and the second Saturday 11 AM, so Wednesday's post is the outlook before
the bids, Thursday's shows the claims that cleared, Friday's follows the Thursday game,
Sunday's follows Saturday's free agency, and Monday's shows the block heading into Monday night.
8:15 AM is after the 8 AM players sync; the times are one line each in the manifest. Ben later
moved Thursday to 11:15 AM, putting waivers clearing at "11 CST", and added Saturday at 11:15 AM
after its round. Sleeper's league setting is `daily_waivers_hour: 8` UTC -- 3 AM Central in
daylight time, 2 AM CST in winter, which is what the rules document says for Thursday -- so the
Thursday clear is earlier than his 11; the 11 AM CST close is the Saturday round. Both are his
call and one line to move. He then dropped Friday as well. The Tuesday and Friday breaks are
deliberate; "today" is therefore the wrong moves
window, which is why moves run since the previous post.

The league sees it as **the Guillotine Daily** -- the header and the file are named so. The
agent, the command and the cron job keep the `eod` codename they were born with, because the
job is registered on the mini by name and a rename would leave the old one firing.

The message shape follows the week:

| Day state | What the message is |
| --- | --- |
| **outlook** — nothing this week has kicked off yet (Tuesday to Thursday) | the projected board, the gulag pair, and who is projected to land on the block |
| **midweek** — some games final, some to come | scores so far, players left, and the odds |
| **final** — every game of the week is over | the standings as they stand, with the block and the gulag result marked provisional pending the commissioner |

Agent name `eod-summary`, recorded through `run_scheduled_with_notes`, so a failing night posts
one note to `#guillotine-ops` on the edge and `ug ops health` carries the standing answer.
`max_gap_minutes` is 1500, the daily budget the run audit already uses.

## Inputs

Before the read, the scheduled run pulls the rosters and the transaction log from Sleeper
itself (`sync_season` and `sync_transactions`, under a savepoint; a failure is one ops note and
the post goes out from what is on file). The two syncs run every ten minutes on their own
phase, and a 10:12 post after a 10:08 waiver clear cannot wait on them. `--no-refresh` skips
it; dry runs never refresh.

All from Supabase, through the Advisor's existing six-query `SnapshotRepository.load()` (rosters,
lineup slots, this week's projections, coverage, FAAB, elimination), joined with:

- `public.team_week_scores` for this week — each team's points, per-starter points, and the
  lineup Sleeper reports — and every earlier week of the season, for the gulag replay below;
- `public.players` for each rostered player's NFL team and injury status;
- `public.league_events` rows of type `gulag_entry` for this week, when an Adjudicator has
  written them;
- `public.transactions` and `public.transaction_moves` since the previous post, for the moves
  line;
- `public.seasons.roster_positions`, for the starter-slot count.

One network read, outside the data layer: Sleeper's public schedule,
`https://api.sleeper.app/schedule/nfl/regular/{season}` (verified 2026-09-10: one object per game
with `week`, `date`, `home`, `away`, `status`; statuses seen `pre_game`, `complete`, `canceled`).
It is the only source of "has this starter played yet", which every odds number depends on. It is
read through a new read-only `SleeperClient.get_schedule(season)`; a failed read is not a failed
run, see Failure Behavior.

## Starter Classification

Each starter slot on each live team is one of:

| Status | Rule |
| --- | --- |
| `empty` | the lineup has fewer filled starter slots than the league's roster positions |
| `out` | injury status in `Out`, `IR`, `PUP`, `Sus`, `COV`, `DNR`; **or** any known flag (`Questionable`, `Doubtful`, `NA`) with no projection — the board's own `outReason` rule, restated so the chat and the site never disagree about who is playing |
| `bye` | the player's NFL team has no game this week |
| `done` | his game is `complete` or `canceled` |
| `remaining` | his game is `pre_game` |
| `live` | any other schedule status (in progress) |

Points so far come from `team_week_scores.players_points`; a starter with no entry has scored
nothing. A team's total is `team_week_scores.points`, never re-derived.

**Coverage is measured over the players who can still score.** A `remaining` or `live` starter
with no projection is a hole; an `out`, `bye`, `done` or `empty` slot is not. The gate is the
Game Pulse spec's: projections for at least 95 percent of rostered unplayed starters across the
live teams, or no percentages are posted. Below the gate the message is factual — scores, ranks,
players left, roster watch — and says why. A single team's unprojected remaining starter does not
fail the league: he is simulated at the median projection of the starters at his position and
that team's line is marked estimated (`~`).

## The Rules Phase

From `docs/rules/ultimate-guillotine-gulag-league-rules.docx`, the season simulation table:

| Week | Kind | Adverse event |
| --- | --- | --- |
| 1 | `entry` | bottom two of the pool enter the Week 2 gulag |
| 2–11 | `gulag` | the lower of the gulag pair is eliminated; bottom two of the rest enter next week's gulag |
| 12 | `double` | the gulag loser and the lowest of the rest are both eliminated |
| 13–16 | `cut` | the lowest remaining team is cut |
| 17 | `final` | the lower of the last two loses the title |
| 18+ | `over` | nothing to post |

**Who is in this week's gulag** is read from `public.league_events` (`event_type = 'gulag_entry'`,
`week` = this week, `payload.team_id`) when an Adjudicator has ruled. Until one exists, it is
replayed from the stored scores: week 1's bottom two form the Week 2 gulag; each later week's
bottom two of the pool (the live teams less that week's gulag) form the next. The replay uses
`team_season_state.eliminated_week` to know who was alive in each past week. It cannot see a
score correction, a commissioner override, or a member paying somebody else to take their place
in the gulag, so a replayed pairing is labelled **provisional** in the message and the
authoritative rows win the moment they exist. If a past week has no scores on file the pairing is
unknown: the message says so, omits the gulag section, and treats every live team as the pool.

Eliminated teams come from `team_season_state.is_eliminated`, whichever source wrote it, and are
listed on one line and left out of every ranking.

## The Survival Model

Deterministic Monte Carlo, pure standard library, model version `mc-2026.1`:

- each team's final = points so far + Σ over `remaining` and `live` starters of
  `max(0, N(μ, σ))`;
- `μ` is the starter's projection (for a `live` starter, `max(0, projection − points so far)`);
- `σ = max(2.0, CV[position] × projection)` with CV `QB 0.35, RB 0.50, WR 0.55, TE 0.60,
  K 0.55, DEF 0.60`, otherwise `0.50`; a `live` starter's σ is scaled by 0.6;
- 10,000 simulations; ties broken by a random key so no team is favoured by row order;
- the adverse event of the phase is evaluated per simulation and the share is the team's odds.

The seed is derived from the SHA-256 input hash (season, week, phase, gulag pair, and every
team's points and starter statuses and projections), so the same inputs always yield the same
odds and a snapshot can be replayed exactly; `--seed` overrides it. Probabilities are kept at
four places and rounded to whole percentages only in the renderer, with `<1%` and `>99%` for the
tails and `locked` when nobody has a player left.

These are estimates, never rulings; the footer names them as Monte Carlo projections and the
runbook and this spec carry the caveat, since Ben asked the post itself to carry no commentary.

## The Message

Two things travel to the chat, under one run: a short text, then a file. Ben (2026-09-10,
after the first dry run): "what I would prefer here is an html that can be sent, similar to a
claude artifact pattern." The text goes first so a member who never opens the file still has
the answer -- the header, the gulag, the block, the sweating list, one line saying the full
board is attached, and the footer -- and the file is the whole summary: the colour, every
section below, the board as a table with the odds as bars. Ben's refinements after the first
real send (2026-09-10): no commentary in the iMessage (the colour leads the file instead), and
every team line as ``<team> · <risk> · proj <finish> · actual <score>``, with the teams sweating
behind the block as their own list rather than one crowded line. It is the League Agent's artifact pattern: tapping the file on
an iPhone opens Quick Look, which renders HTML with inline CSS and nothing else.

The full deterministic text below is still composed on every run: it is what the colour is
written over and checked against, and what the recap's facts hash covers. In order:

1. **Header** — `🗡️ GUILLOTINE EOD · Week N · Sunday`, then one line on the day: games final
   this week, teams with players still to play.
2. **Colour** (optional) — a headline and one or two sentences from the model, see below.
3. **On the block** — the two teams currently in the adverse position, each as risk, projected
   finish and actual score; then **Sweating**, the same line for anyone else at 10 percent or
   more. In a gulag week this is preceded by **the gulag**: the pair, each one's odds of losing,
   projected finish and score. Before kickoff the actual score is left off; in factual mode the
   risk and the projection are.
4. **The board** — every live team, ranked by projected finish (points so far plus remaining
   projection): rank, label, score, projected finish, players left, odds. In `outlook` the score
   and the players-left column are dropped and the projected total stands alone. Eliminated
   teams follow on one line: `Out: A (wk 3), B (wk 4)`.
5. **Roster watch** — only teams with something to fix: empty slots, out starters still in the
   lineup, remaining starters with no projection. At most eight lines; the rest as a count.
6. **Moves since the last post** — adds, drops and trades executed since the previous post
   went out (a day back when there is none; never more than four days), at most six lines in
   the text, all of them in the file. The heading names the window: `MOVES SINCE FRI 8:15 AM`.
7. **Footer** — `Monte Carlo projections as of 9:20 AM CST` and nothing else (Ben's ruling,
   2026-09-10: "no further commentary"); in factual mode `No Monte Carlo odds: <reason> · data
   as of <time>`. The time is the newest input sync, written as CST all season as the rules do.

Members are named by their public label (`coalesce(nickname, sleeper_display_name,
display_name)`) exactly as the board does; the join key is never rendered. Every string comes
from public tables or from numbers this run computed. The delivery layer appends the signature.

## The Artifact

`summary/artifact.py` renders the same `View` the text renderer reads -- the same ranks, pairs
and notes, so the two cannot disagree -- into one self-contained page: the board's own palette
written inline, a hero, the colour card, the gulag and block cards with each team's standing and
odds, the board table (rank, score, projected finish, players left, risk with a bar; the gulag
pair marked ⚔, an estimated finish marked ~), the roster watch and the moves. No script, no
image, no stylesheet link, no font, no URL of any kind; every string from a model or a member's
Sleeper profile is HTML-escaped; the file is capped at 200 KB. It is named
`guillotine-eod-week-<N>-<local date>.html`.

## The Colour

One structured call through `HermesStructuredClient`, prompt `agents/eod-summary/prompt.md`
(version `2026.1`), schema `EodColor` — a headline of at most 90 characters and a blurb of at
most 300. It is handed the rendered sections 3 to 6 as its facts and nothing else. The verifier
then checks that every number in the headline and blurb appears among the packet's numbers (a
score, a percentage, a rank, a count), that neither carries a phone, email, chat identifier, URL
or the word "dues", and that the caps hold. A rejected colour is dropped, the deterministic
message goes out without it, and the reason goes to `#guillotine-ops`. A Hermes outage, a
missing CLI, or `--no-ai` likewise means no colour and a run that still succeeds. The model
decides nothing: it cannot add a team, move a rank, or change a number the verifier can see.

## Storage and Idempotency

No migration. Two foundation tables were built for exactly this:

- `public.survival_snapshots` — one row per run: `game_window = 'eod:<local date>'`,
  `model_version`, `simulations`, `input_hash`, `projection_source = 'sleeper'`, and `results`
  as one entry per team (team id, label, points, projected finish, players left, adverse event,
  probability, whether estimated). The unique key on `(season, week, window, input hash, model)`
  makes a re-run over unchanged inputs a no-op insert.
- `public.recaps` — one row per composed message: `recap_kind = 'eod:<local date>'`,
  `prompt_version`, `facts_hash` (over the deterministic text), `body` exactly as sent, and
  `publication_state` `draft` until delivery succeeds, then `sent`.

**One post a day.** Before sending, the agent asks whether a `recaps` row of today's kind is
already `sent`; if so it prints `already sent` and exits 0 without composing again. `--force`
overrides that for rehearsal in test mode. The run itself is keyed per UTC minute through
`run_scheduled`, so a failed night can be re-run from `/cron run guillotine-eod-summary` without
the failed reservation blocking it. The run's `input_version` records `mc-2026.1` plus the
prompt version and model when a colour was used.

## Delivery

Through `DeliveryService`, with the reserve → commit → send → reconcile path every other agent
uses, under the run's id and agent `eod-summary`: the short text through `deliver`, then the
file through `deliver_attachment` (the League Agent branch's attachment path, brought over
unchanged: multipart to BlueBubbles, reserved and reconciled by file name like text). In `test`
mode that is the self-test chat; in `production` the league chat; in `disabled` nothing is sent
and the recap stays a draft. A file that fails to send after the text went out is one ops note
and a run that still succeeds: the chat has the answer.

Whatever the mode short of production, the composed message is also posted to
`#guillotine-drafts` first, as the foundation asks of test-mode previews, so Ben sees tomorrow
night's post in Discord even before the chat target is proven. The feed mirror in test and
production comes from the delivery layer as today.

## Commands

- `ug summary eod` — the scheduled run: load, simulate, compose, store, deliver, record.
- `ug summary eod --dry-run` — everything but the writes and the sends: prints the chat text,
  writes the artifact to `--out DIR` (default: the current directory) and prints its path,
  records no run, posts nowhere. Still calls the model unless `--no-ai`.
- `ug summary eod --json` — prints the fact packet (every team's line and odds) and makes no
  model call.
- `ug summary eod --fixture` — answers out of a closed-form league (the Advisor's fixture plus
  fabricated scores, injuries and a half-played schedule), so the message shape can be checked
  on a machine with no database, no Sleeper and no Hermes. Implies `--dry-run`.
- `--no-ai`, `--seed N`, `--simulations N`, `--force`, `--quiet`.

## Failure Behavior

| Condition | Behaviour |
| --- | --- |
| off-season (`season_type != regular`) | prints `eod: skipped, season_type=…`, exits 0 |
| week 18 or later | prints `eod: skipped, season over`, exits 0 |
| no snapshot (no state row, no teams, no projection row) | run `failed`, reason printed, one ops note on the edge |
| schedule unreachable | factual message, no odds, footer says game status was unavailable |
| coverage over remaining starters below 95 percent | factual message, no odds, footer names the coverage |
| scores row missing for a team | that team reads 0 with every starter `remaining`, and the footer says scores were missing |
| past-week scores missing for the gulag replay | gulag section omitted, pairing reported unknown |
| Hermes down or colour rejected | message without colour; reason to ops; run succeeds |
| delivery disabled | recap stored as `draft`, drafts preview posted, run succeeds |
| delivery target mismatch | recap stays `draft`, run `failed`, alerts note |
| already sent today | `already sent`, exit 0 |
| crash after send | the next run's delivery reconciles by content hash as every agent does |

## Privacy and Safety

Everything rendered is public Sleeper data or arithmetic over it. No handle, hash, chat GUID,
phone, email, dues value or `display_name` join key can reach the message: the labels come from
the same columns the public board renders, the model is handed the rendered facts only, and its
output is scanned before use. Ops and alerts notes carry statuses, exception names and rejection
reasons — never the message text, which is the league's.

Pressure is public here. The board already ranks every team by projection, and this is a
guillotine league: saying who is on the block is the whole point, per Ben's League Agent ruling
that the old Advisor rule against naming another team's pressure is dropped.

## Package Layout

```text
ultimate_guillotine/summary/
  models.py     StarterLine, TeamLine, Phase, TeamOdds, SurvivalResult, EodPacket, EodSnapshot
  schedule.py   the schedule feed: parse, per-team game for a week, day state
  lineup.py     starter classification, coverage over remaining starters
  phase.py      the rules table and the gulag pairing (events, else replay)
  survival.py   the Monte Carlo, input hash, seed
  snapshot.py   EodRepository (the reads) and assemble() (pure)
  render.py     the deterministic message, and the View both renderers read
  artifact.py   the HTML file and the short chat text that travels ahead of it
  color.py      EodColor, the prompt call, the verifier
  store.py      survival_snapshots and recaps writes, the once-a-day check
  fixture.py    the closed-form league with scores and a half-played week
  agent.py      EodSummaryAgent: build → simulate → compose → store → deliver
cli/summary.py  ug summary eod
agents/eod-summary/prompt.md, README.md
hermes/guillotine/scripts/guillotine_eod_summary.sh.template
```

`SleeperClient` gains `get_schedule(season)`. Nothing under `advisor/` changes; the snapshot is
imported from its current home and moves with it when the League Agent relocates it.

## Testing

Offline by default. Pure tests for the schedule parser, every starter status, the coverage gate,
the rules table, gulag pairing from events and from replay (including a missing week and an
eliminated team's past weeks), seeded determinism and the obvious cases of the simulation (a team
with nothing left and the lowest score is on the block at 100 percent; a gulag pair's odds sum to
one; week 12's two events; the direct cut), the renderer (every section, whole percentages,
factual mode contains no percentage, no join key, the caps), the colour verifier (an invented
number, a phone number, an over-length blurb each rejected; a faithful blurb accepted), and the
CLI in a subprocess with `--fixture` and no database, Hermes or Sleeper in reach. Database tests
over the local Supabase for the two repositories. The cron manifest test learns the new agent.

## Rollout

1. `pnpm test:agents` and `pnpm lint:agents` green; `ug summary eod --fixture --no-ai` prints a
   message Ben likes the shape of.
2. On the Mac mini: `hermes/guillotine/install.sh` (registers the job and the expected run),
   then `ug summary eod --dry-run` against the real league to read tonight's message.
3. The first scheduled run lands in `#guillotine-drafts` and the self-test chat (test mode).
4. Production is Ben flipping `DELIVERY_MODE`, as for every agent; nothing here is
   production-specific.

## Decisions Taken Without Ben

| Question | Decision | Where to change it |
| --- | --- | --- |
| Post time | 8:15 AM Central on Ben's five mornings (his ruling); the hour is mine | `hermes/guillotine/cron.yaml` |
| Model in the loop? | Yes, for a headline and blurb only, verified, with the deterministic message as the fallback | `--no-ai`, `agents/eod-summary/prompt.md` |
| Variance model | Position CVs with a 2-point floor, 10,000 sims | `summary/survival.py` constants |
| Gulag pairing before an Adjudicator exists | Replay from stored scores, labelled provisional | `summary/phase.py` |
| Once a day | A `sent` recap row of today's kind blocks a second post | `summary/store.py`, `--force` |
| Where the preview goes | `#guillotine-drafts` in every mode but production | `summary/agent.py` |
| Naming | agent `eod-summary`, command `ug summary eod` | throughout |
| Text or file | Ben's ruling: a short text then the HTML artifact; the file holds the board | `summary/artifact.py` |

## Out of Scope

- Official rulings, eliminations, or gulag entries: the Weekly Adjudicator's.
- The weekly narrative recap: the Storyteller's.
- Game-window posts after each slate (Game Pulse), which would be extra schedules of this command.
- Any page on the site; `survival_snapshots` is public and readable if the board ever wants it.
- Answering questions; the League Agent does that.
