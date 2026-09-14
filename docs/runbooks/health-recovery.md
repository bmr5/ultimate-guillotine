# Automatic health recovery

The Mac's existing five-minute health job runs:

```sh
ug ops health --auto-recover --changes-only --escalate
```

If the configured BlueBubbles endpoint is local, its ping fails, and the
BlueBubbles process is absent, the check opens `/Applications/BlueBubbles.app`
in the background and verifies its authenticated ping. It does not force-quit
a running app. Remote servers and missing applications require manual review.

Launch attempts are at least 15 minutes apart, with at most three per outage.
A successful ping resets the retry budget. State lives in
`~/.hermes/profiles/guillotine/health-state.json`, protected by a file lock and
atomic writes. The attempt is saved before launch so an interrupted check still
counts. A corrupt state file stops the check rather than resetting the budget.

Health alerts go only to the configured Discord alerts channel. New issues and
resolved issues produce notifications. Changing run timestamps and increasing
job ages do not repeat an unchanged warning. A failed notification is retried on
the next check. Hermes retains full output locally, with this job's delivery set
to `local` to avoid a second copy in the ops channel. Other jobs retain their
existing failure and recovery notes.

Recovery does not resend summaries, replay trades, resolve uncertain sends,
change database records, or restart other services. Regular message sync resumes
on its existing schedule when BlueBubbles returns. A failed daily summary remains
reported until it has a subsequent successful run.

For a diagnostic check without recovery or Discord delivery, use `ug ops health`.
To exercise recovery without a Discord notification, add `--auto-recover` only.

Validation on September 14, 2026: the recovery code reopened the stopped local
BlueBubbles application and its authenticated ping succeeded. Automated tests
cover the retry budget, cooldown, running-app protection, remote endpoints,
persisted state, failed notification retries, and notification deduplication.
