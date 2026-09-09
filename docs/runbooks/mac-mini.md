# Mac mini installation runbook

This runbook installs the Ultimate Guillotine automation stack on the
always-on Mac mini: the hosted Supabase project, BlueBubbles Server, the
`ug` listener under `launchd`, and the `guillotine` Hermes gateway. Run
every repository command from the repository root. Never write a real
chat GUID, phone handle, token, or password into this file — every value
below is a placeholder to fill in locally, in `.env` or `~/.hermes/profiles/guillotine/.env`,
never in Git.

## 1. Hosted Supabase

**Everything in steps 1a to 1c runs on Ben's development machine, in his
own checkout — never on the Mac mini.** The superuser database password
and the Supabase access token are what schema migrations and role
creation need; the Mac mini is a least-privilege worker and must never
hold either one. The only Supabase secret that ever reaches the mini is
the worker `DATABASE_URL` written in step 1e.

### 1a. Create the project (development machine)

Ben creates the free Supabase project under his personal account and
notes its project ref from the dashboard.

### 1b. Link and push the schema (development machine)

The development checkout already has `SUPABASE_ACCESS_TOKEN` and
`SUPABASE_DB_PASSWORD` in its repo-root `.env`. Pass them on the command
line rather than running the machine-wide `supabase login`, so that login
can stay pointed at other projects:

```bash
SUPABASE_ACCESS_TOKEN=<value from repo .env> \
SUPABASE_DB_PASSWORD=<value from repo .env> \
supabase link --project-ref <ref>

SUPABASE_ACCESS_TOKEN=<value from repo .env> \
SUPABASE_DB_PASSWORD=<value from repo .env> \
supabase db push
```

### 1c. Create the worker login (development machine)

Create the `ultimate_guillotine_mac` worker login by running
`scripts/configure_worker_role.sql.example` through `psql`, connected via
the project's Supavisor **session pooler** (not the direct connection
`db push` uses) — the pooler host and port come from the dashboard's
Connect panel:

```bash
openssl rand -hex 24   # generate the worker password once

psql "<Supavisor session pooler connection string from the dashboard Connect panel>"
```

At the `psql` prompt:

```sql
\set worker_password '<the password just generated>'
\i scripts/configure_worker_role.sql.example
```

### 1d. Confirm the private schema is not exposed (dashboard)

In the dashboard, open **Settings → API → Exposed schemas** and confirm
the list is `public` and `graphql_public` only. `private` must not appear
there: everything in it — chat GUIDs, hashed handles, message excerpts,
outbound content — would otherwise be reachable over PostgREST.

### 1e. Give the Mac mini its worker URL (Mac mini)

On the Mac mini, write only `DATABASE_URL` for the worker login into the
repo `.env`. Because the Supavisor session pooler expects the role name
suffixed with the project ref, the URL takes the form:

```
DATABASE_URL=postgresql://ultimate_guillotine_mac.<ref>:<generated password>@<pooler host from the Connect panel>:5432/postgres
```

The mini's `.env` must never contain `SUPABASE_DB_PASSWORD` or
`SUPABASE_ACCESS_TOKEN`. Nothing on the mini runs `supabase link`,
`supabase db push`, or any migration; it only connects as the worker.

Confirm with `uv run --project packages/league-automation ug ops doctor` —
the `database` check should report `PASS`.

## 2. BlueBubbles Server

Download BlueBubbles Server from [bluebubbles.app](https://bluebubbles.app)
and install it. Sign in to Messages.app with Ben's Apple ID first, then
open BlueBubbles Server and:

- Grant Full Disk Access and Automation when macOS prompts for them.
- Set a server password.
- Leave the Private API off.
- Note the local server URL (default `http://127.0.0.1:1234`).

Write into the repo `.env`:

```
BLUEBUBBLES_SERVER_URL=http://127.0.0.1:1234
BLUEBUBBLES_PASSWORD=<the server password just set>
```

Generate the webhook password:

```bash
openssl rand -hex 24
```

Write it into `.env` as `WEBHOOK_PASSWORD=<generated value>`.

## 3. Self-test chat

Create a group iMessage chat containing Ben and one other Ben-controlled
handle. Find its GUID with BlueBubbles' chat query endpoint:

```bash
curl -s -X POST "$BLUEBUBBLES_SERVER_URL/api/v1/chat/query?password=$BLUEBUBBLES_PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{"limit": 20, "with": ["participants"]}' \
  | python3 -m json.tool
```

Find the self-test chat in the output and copy its `guid`. Store it as
the test delivery target:

```bash
uv run --project packages/league-automation ug targets set \
  --mode test --chat-guid "<guid from the query above>" --label self-test
```

Write into the repo `.env`:

```
DELIVERY_MODE=test
TEST_CHAT_GUID=<the same guid>
```

Member phone numbers live only inside BlueBubbles Server and in `.env` —
never in Git, and never in this file.

## 4. Listener

Install and start the listener under `launchd`:

```bash
scripts/mac-mini/install_listener.sh
```

Register the webhook with BlueBubbles Server:

```bash
uv run --project packages/league-automation ug ops register-webhook
```

Confirm with `uv run --project packages/league-automation ug ops doctor` —
the `listener_healthz` and `listener_heartbeat` checks should report
`PASS`.

## 5. Discord

1. Create the four channels in the Agent HQ Discord server:
   `#guillotine-ops`, `#guillotine-feed`, `#guillotine-drafts`, and
   `#guillotine-alerts`.
2. In the Discord Developer Portal, create a second bot application named
   **Guillotine Ops**, with the Message Content and Server Members
   intents enabled.
3. Invite that bot to the server with the View Channels, Send Messages,
   Read Message History, and Attach Files permissions.
4. Install the Hermes profile:

   ```bash
   hermes/guillotine/install.sh
   ```

5. Paste into `~/.hermes/profiles/guillotine/.env`:

   ```
   DISCORD_BOT_TOKEN=<Guillotine Ops bot token>
   DISCORD_HOME_CHANNEL=<the #guillotine-ops channel id>
   DISCORD_ALLOWED_USERS=<Ben's Discord user id>
   ```

6. Install the gateway:

   ```bash
   HERMES_HOME=~/.hermes/profiles/guillotine hermes gateway install
   ```

7. Confirm both profiles are running:

   ```bash
   hermes gateway list
   ```

## 6. Gate 0

Gate 0 is run and recorded separately, after this installation is
complete (see Steps 3 and 4 of the plan's Task 13). The checklist below
is copied verbatim from the plan; check each box off as it is verified
on the Mac mini, and update the status heading below once every box is
checked.

### Gate 0 passed: 2026-09-08, delivery mode test

- [x] Delivery: `ug ops self-test` prints `sent`; exactly one signed
  `Self-test ...` message appears in the self-test chat; `#guillotine-feed`
  shows the mirror.
- [x] Inbound: send `@bot ping` in the self-test chat from the non-Ben
  handle; a signed `pong ...` reply arrives within 10 seconds;
  `#guillotine-feed` shows it.
- [x] Scheduler: `HERMES_HOME=~/.hermes/profiles/guillotine hermes cron run
  <id of guillotine-health>` completes with status `ok` in `hermes cron
  list`, and `#guillotine-ops` receives either nothing or a problem list;
  `ug ops audit-runs` prints nothing for `guillotine-health`.
- [x] Crash replay: `ug ops self-test --crash-after-send` exits non-zero
  after one message is sent; run `ug ops self-test` again within the same
  minute; it prints `reconciled`; the chat shows exactly one new message
  for that minute.
- [x] Webhook replay: re-send the last webhook payload with `curl` from
  the listener log's recorded GUID; the response is
  `{"outcome":"duplicate"}`.
- [x] Gap fill: stop the listener with `launchctl bootout
  gui/$(id -u)/com.ultimateguillotine.listener`, send `@bot ping` in the
  self-test chat, restart with the installer, run `ug ingest gap-fill`;
  exactly one `pong` arrives and a second `ug ingest gap-fill` handles
  zero messages.
- [x] Doctor: `ug ops doctor` exits 0.

Notes from the 2026-09-08 run:

- The self-test chat is a two-person group; the second handle sent the
  inbound pings. The second `ug ingest gap-fill` in the same minute is a
  no-op by design (idempotency key), which also guarantees no second
  reply.
- Discord delivery for the scheduler check was verified after the
  `guillotine` gateway was installed and connected; before that, cron
  runs reported `delivery_failed` with "platform 'discord' not
  configured/enabled", which is expected.
- `ug ops doctor` reported 10 of 10 PASS.

Once every check above passes, replace the status heading with
`Gate 0 passed: <date>, delivery mode <test|production>` and leave the
checked boxes as the record. Do not record GUIDs or handles here or
anywhere else in this file.

## 7. Recovery

**Re-run a missed job.** From Discord, in `#guillotine-ops`, send
`/cron run <job name>` (for example `/cron run guillotine-health`) to
trigger an immediate run of that job outside its schedule.

**Re-run a trade the registrar left stuck.** `ug ops health` prints
`runs stuck running > 15m: N (agent trade-registrar)` when a run was
reserved and never finished — the agent died between the two, so nothing
was recorded and nothing was said in the chat. The idempotency key of
such a run is `trade:<source guid>`; re-run that candidate with:

```bash
uv run --project packages/league-automation ug trades retry <guid>
```

It reserves a fresh run under a per-attempt key, so the stuck one does
not block it. The stuck row stays as the record of the crash.

**Read listener logs.** The listener's stdout and stderr are written to:

```
~/Library/Logs/UltimateGuillotine/listener.out.log
~/Library/Logs/UltimateGuillotine/listener.err.log
```

Tail them with `tail -f` while reproducing an issue.

**Rotate the BlueBubbles password.** Set a new password in BlueBubbles
Server's settings, update `BLUEBUBBLES_PASSWORD` in the repo `.env`, then
re-register the webhook (the webhook URL embeds `WEBHOOK_PASSWORD`, not
the BlueBubbles password, so it does not need to change):

```bash
uv run --project packages/league-automation ug ops register-webhook
```

Restart the listener so it picks up the new `.env` value:

```bash
scripts/mac-mini/install_listener.sh
```

## 8. Trade Registrar rollout

The Trade Registrar listens for `🚨` alerts in the league chat and logs
one trade (or asks one question) per announcement. It ships behind its
own gate, run after Gate 0 and after the listener has been restarted
with `DELIVERY_MODE=test`. The checklist below is copied verbatim from
the plan's Task 9, Step 4; check each box off as it is verified on the
Mac mini, and rename the status heading once every box is checked.

### Gate pending

With `DELIVERY_MODE=test` and the listener restarted. Test mode writes
trade codes prefixed `TEST-`, counted in their own sequence, so
rehearsing the gate never consumes a real trade number: the league's
first real trade is still `T-2026-001`. The gate rows stay in
`public.trades` and `public.trade_revisions` until Ben deletes them from
the Supabase dashboard afterwards — the automation worker holds no
DELETE grant on those tables by design, so nothing in this repository
can clear them.

- [ ] Send `🚨 Trade Alert 🚨` on one line and `<Ben> sends Player Alpha
  to <second handle name> for 100 FAAB` on the next, from the second
  handle, using two real member display names from `public.members` and
  a real active player name. Expect a signed `🚨 Trade TEST-2026-001
  logged` reply and a mirror in `#guillotine-feed`.
- [ ] Send the same text again. Expect no reply; `ug ops audit-runs`
  prints nothing; `select status from private.agent_runs where agent =
  'trade-registrar' order by id desc limit 1` is `duplicate`.
- [ ] Send the same trade with a different FAAB amount. Expect
  `🚨 Trade TEST-2026-001 updated`.
- [ ] Send `🚨 Trade TEST-2026-001 is rescinded`. Expect
  `🚨 Trade TEST-2026-001 rescinded`.
- [ ] Send `🚨 Player Alpha rented for 10`. Expect a clarification reply
  and no new trade.
- [ ] Restart the listener between the send and the run completion once
  (`launchctl kickstart -k` immediately after step 1's send) and confirm
  exactly one confirmation exists; re-post the webhook payload with the
  recorded GUID and confirm `duplicate`.
- [ ] `ug trades list` shows the trade with status `rescinded` and
  revision 2.

Once every check above passes, replace the status heading with
`Gate passed: <date>, delivery mode <test|production>`, leave the checked
boxes as the record, and add the outcomes as notes below it. Do not
record GUIDs or handles here or anywhere else in this file. Production
promotion (`DELIVERY_MODE=production` and a production target) is a
separate, explicit decision by Ben after this gate.

### Replay history

`ug trades replay` runs a season of past announcements out of the
contracts spreadsheet through the same pipeline the listener uses. It is
how a prompt or resolution change is measured against real history
rather than against invented examples.

Dry run — resolves only, writes nothing, sends nothing, and costs one
model call per candidate row:

```bash
uv run --project packages/league-automation ug trades replay \
  history/contracts/2025-26/all-contracts.xlsx --dry-run --limit 15
```

Write mode — no `--dry-run` — runs the registrar for real and fills the
trade tables from history. It never sends, whatever the delivery mode,
and it exits 2 without writing anything when `DELIVERY_MODE` is
`production`: replaying a past season into the live league would be
indistinguishable from a flood of new trades. It also exits 2 with `no
public.seasons row for 2025; insert it first` when that season has no
row — every trade hangs off its season, so without it each row would
cost a model call and fail. Failures are printed as `row N: failed` and
nothing is posted to Discord: a replay of a past season fails on rows
nobody is going to fix, and alerting on each one would page for
history. Run it only with `DELIVERY_MODE` set to `disabled` or `test`:

```bash
uv run --project packages/league-automation ug trades replay \
  history/contracts/2025-26/all-contracts.xlsx
```

Each row prints `row N: <outcome>`, where the outcome is one of:

| Outcome | Meaning |
| --- | --- |
| `created` | a new trade was logged |
| `duplicate` | the same terms were already on file |
| `revised` | an existing trade was updated with new terms |
| `rescinded` | an existing trade was rescinded |
| `clarification: <reason>` | the registrar would have asked the chat this |
| `duplicate` (write mode) | the same text or terms were already recorded |
| `not-a-trade` | the model read the row as chatter |
| `not-a-candidate` | the `🚨` trigger would never have looked at the row |
| `failed` | the row raised; the run is recorded `failed` |
| `skipped` | the run key was already reserved, so nothing ran |

Only `--dry-run` can spell the reason out: it has the `Unresolved` in
hand. Write mode goes through the registrar, which answers with its
status alone, so those rows print a bare `clarification` — the question
it would have asked is in the chat message it did not send, not in the
replay output.

A summary line closes the run. It always names `created`, `duplicate`,
`clarification`, and `not-a-candidate`, then appends any of the others
that happened, so the counters always add up to the row count. The shape,
with an illustrative set of numbers:

```
replay: 18 rows, created 11, duplicate 0, clarification 6, not-a-candidate 1
```

Clarifications are expected wherever 2025 member or player names differ
from the 2026 `public.members` and `public.players` tables — the
registrar is asking about a name that no longer exists, which is correct
behaviour, not a bug to fix here.

Running a write-mode replay a second time reports `skipped` for every
row and changes nothing: the run key is `trade:replay:<hash of the row
text>`, so the first replay already reserved it. That is the intended
guard, not a failure — to replay the same workbook again for real, the
earlier runs have to be cleared first.
