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

## Fill gaps in ingested data

```
cd <repo> && uv run --project packages/league-automation ug ingest gap-fill
```

## Rules

Never paste secrets or chat identifiers into Discord. If a command's
output contains anything that looks like a token, phone number, or chat
ID, summarize around it instead of quoting it verbatim.
