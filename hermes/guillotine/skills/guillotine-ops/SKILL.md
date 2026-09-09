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

## Ask the Trade Advisor a question without sending anything

```
cd <repo> && uv run --project packages/league-automation ug advisor ask \
  --text "<question>" --as <member>
```

A safe dry run: it prints the advice the league would have seen and writes
nothing, sends nothing, and records no run.

In the chat the Advisor answers **only in the self-test chat**, and only when a
message tags `@bot` and asks for advice rather than a fact — a lookup question
goes to the Concierge. Promoting it to the league chat is a code change to
`advisor_chat_guid` in `listener/run.py`, reviewed like any other, not a row
somebody adds to `private.delivery_targets`.

It never registers a trade. Announce a trade with a 🚨 alert and the Trade
Registrar logs it.

## List league members and how many nicknames each has

```
cd <repo> && uv run --project packages/league-automation ug members list
```

Prints one line per member with a count only; it never prints a nickname.
`ug members aliases load <file>` replaces every listed member's nicknames from
a JSON file and reports counts only. `ug members handles load <file>` does the
same for the Apple handles the Advisor matches a sender by: only the hash of
each handle is stored, and the command prints counts only — never a handle.

## Fill gaps in ingested data

```
cd <repo> && uv run --project packages/league-automation ug ingest gap-fill
```

## Rules

Never paste secrets or chat identifiers into Discord. If a command's
output contains anything that looks like a token, phone number, or chat
ID, summarize around it instead of quoting it verbatim.
