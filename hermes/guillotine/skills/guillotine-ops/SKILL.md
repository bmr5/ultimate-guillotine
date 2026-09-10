---
name: guillotine-ops
description: Run Ultimate Guillotine league operations CLIs and report their output plainly.
---

# guillotine-ops

Commands for operating the Ultimate Guillotine fantasy league. Run every
command from the repository directory, `<repo>`, using `uv run` against
the `packages/league-automation` project.

All commands below are safe to re-run at any time. None of them mutate
league data destructively, and running one twice causes no harm.

Output is the whole result. Empty output means there was nothing to
report — it does not mean the command failed. Never guess at what a
command "probably" would have said; only report what it actually printed.

## Check overall health

```
cd <repo> && uv run --project packages/league-automation ug ops health
```

## Audit recent automation runs

```
cd <repo> && uv run --project packages/league-automation ug ops audit-runs
```

## Run the self-test suite

```
cd <repo> && uv run --project packages/league-automation ug ops self-test
```

## Run diagnostics

```
cd <repo> && uv run --project packages/league-automation ug ops doctor
```

## Sync Sleeper league data

```
cd <repo> && uv run --project packages/league-automation ug sleeper sync
```

## Refresh the NFL week

```
cd <repo> && uv run --project packages/league-automation ug sleeper state
```

Prints the season, the season type, and the week — `2026 regular week 3`. The
week is scoped by season type: `pre 2` is preseason week 2, not week 2 of the
season.

## Sync this week's projections

```
cd <repo> && uv run --project packages/league-automation ug sleeper projections
```

Fetches the week `nfl_state` reports, scores it with the league's settings, and
recomputes every team's projected points. Prints the player count, how many went
unscored, and the run's coverage percentage. Outside the regular season it does
nothing and says so (`projections: skipped, season_type=pre`) — a no-op, not a
failure, so the half-hourly job stays green all winter. It does refuse a payload
too thin to be a real week, rather than blanking a week that already has good
numbers.

`--week N` syncs a specific week. `--rescore` recomputes points from the stat
lines already stored, with no call to Sleeper — that is the command to run after
the league's scoring settings change, never a re-sync.

Coverage below 95% and a scoring-drift warning each post one note to
`#guillotine-ops` — only when the week's flagged state actually changes, in
either direction, since this job fires every five minutes during a game window.
The numbers are still written, flagged, never withheld.

## List recently logged trades

```
cd <repo> && uv run --project packages/league-automation ug trades list
```

## Re-run a trade announcement the registrar failed on

Takes the source GUID reported in the failure.

```
cd <repo> && uv run --project packages/league-automation ug trades retry <guid>
```

`ug trades extract --text "<announcement>"` is a safe dry run: it prints what
the registrar would record and writes nothing, sends nothing.

`ug trades replay <xlsx> --dry-run` is the same dry run over a whole season of
past announcements from a contracts spreadsheet; it writes nothing and sends
nothing.

## Ask the League Agent a question without sending anything

```bash
cd <repo> && uv run --project packages/league-automation ug agent ask \
  --text "<question>" --as "<member label>" --out /tmp/league-agent
```

This dry run prints the answer and writes any HTML artifact to `--out`. It sends
no messages and records no run, session, or answer in the database. Real-league
asks use a read-only connection. `--as` accepts a member label or alias and exits
2 if the name is unknown or ambiguous.

Use `--fixture --as Member01` for synthetic league data without a database.
It still calls Hermes and requires authentication in the league profile.
Set `HERMES_MODEL` to override the model; `--resume <session id>` continues a
Hermes session. There is no `--json` mode.

Read recorded answers with `ug agent answers --last 5`. Keep private question
and answer text out of Discord ops notes; report statuses and failure reasons.

The agent answers any `@bot` question or inline reply in the self-test chat.
Promotion requires editing `agent_chat_guid` in `listener/run.py` after the
runbook's acceptance gates pass. See section 10 of `docs/runbooks/mac-mini.md`
for profile installation, authentication, MCP checks, and rollout status.

It never registers a trade. Announce a trade with a 🚨 alert for the Trade Registrar.

## Compose tonight's EOD summary without sending

```
cd <repo> && uv run --project packages/league-automation ug summary eod --dry-run
```

A safe dry run: it prints the nightly post's chat text -- the gulag pair, who is
on the block and their odds -- and writes the full summary (every team's score and
projected finish, the roster problems, the day's moves) as an HTML file to
`--out DIR`, the current directory by default. It sends nothing to the chat and
records no run. `--no-ai` skips the model's headline; `--json` prints the fact
packet instead and makes no model call; `--fixture` answers out of the built-in
league with no database at all.

The scheduled job (`guillotine-eod-summary`, 8:15 AM on Wednesday, Sunday and
Monday, and 10:12 AM on Thursday and Saturday) posts the same thing to the chat through the delivery
layer and previews the text in `#guillotine-drafts`. Run again the same day it
prints `eod: already_sent`; `--force` posts again.

## List league members and how many nicknames each has

```
cd <repo> && uv run --project packages/league-automation ug members list
```

Prints one line per member with a count only; it never prints a nickname.
`ug members aliases load <file>` replaces every listed member's nicknames from
a JSON file and reports counts only. `ug members handles load <file>` does the
same for the Apple handles the League Agent matches a sender by: only the hash of
each handle is stored, and the command prints counts only — never a handle.

## Fill gaps in ingested data

```
cd <repo> && uv run --project packages/league-automation ug ingest gap-fill
```

## Rules

Never paste secrets or chat identifiers into Discord. If a command's
output contains anything that looks like a token, phone number, or chat
ID, summarize around it instead of quoting it verbatim.
