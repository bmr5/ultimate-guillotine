# Trades API

`GET https://ultimate-guillotine-sage.vercel.app/api/trades` returns JSON schema
version 2. Optional `?season=2026` filters registrations, catalog, teams and
executions. Without the filter, all available seasons are returned. Rescinded
registrations are retained; `TEST-` trade codes are excluded.

- `registered_trades`: latest terms, original announcement, registration status,
  announcement and recording dates, revision, effective week, parties and assets.
- `historical_catalog`: historical source records, dates/weeks, player and party
  IDs where recorded, and confidence. Unknown IDs remain null.
- `deals`: registrations plus catalog entries whose catalog IDs are not already
  registered trade codes. This removes exact source-ID overlap, not every possible
  duplicate. It is not a certified unique economic-deal count.
- `sleeper_executions`: distinct platform transaction IDs, recorded completion
  status, processing date/week, player transfers, FAAB transfers and sync time.
  These are evidence about deals, not extra deals to add to the announcement count.
- `members`, `teams`, `players`: ID directories. Internal team IDs, member IDs,
  Sleeper roster IDs and Sleeper player IDs are explicitly distinguished.
- `deduplication`: exact catalog/registration overlaps and unlinked executions.

Each announced/cataloged deal has `finances.rental_fees`, `deposits`, `refunds`,
`other_payments`, and `unclassified_payments`. Only explicit structured amounts
are categorized. Combined or unspecified payment purposes stay unresolved.
Missing amounts are null, not estimated or zero. Amounts are not assigned to
individual players in packages. Conditional refunds explicitly quoting a recorded
deposit amount are exposed separately with `conditional_not_verified`; this does
not assert that a refund actually happened. Sleeper cash transfers cannot establish
their contractual purpose and remain unclassified. Original terms and source
descriptions are preserved for further review; extraction completeness is unverified.

An accepted registration does not establish execution or fulfillment of every rental
obligation. Completion status for announcements/catalog is therefore unverified.
Execution records expose Sleeper's own status. Candidate links require the same season,
parties, full directed player transfers and aggregated directed FAAB movements within
72 hours of the announcement. Links remain `candidate_only`, including when unique;
there is no durable confirmed contract/execution mapping in the source data.
Unlinked executions may be returns, unannounced deals or unresolved matches. Never
silently count them as new purchases or assume all announcements settled.

Send the secret in `X-API-Key` or `Authorization: Bearer ...`. Keys in URLs are not
accepted. Responses use `Cache-Control: private, no-store`. Only GET is supported.
No private schema, source-message GUID, administrator key or database connection
string is returned. Registered terms include the league's original announcement.

Server-only production environment variables:

- `TRADES_API_KEY`: randomly generated, separately revocable client credential.
- `TRADES_DATABASE_URL`: dedicated `league_trades_api` session-pooler login with
  SELECT on `trades`, `trade_revisions`, `trade_catalog`, `seasons`, `members`,
  `teams`, `players`, `transactions`, and `transaction_moves`.
  This login has no write grants, no private schema access, and defaults to
  read-only transactions. Do not reuse a worker or administrator account.

The function additionally opens a repeatable-read, read-only transaction. TLS
verifies the server certificate using the public Supabase Root 2021 certificate
in `api/supabase-ca.crt`, downloaded from
`https://supabase-downloads.s3-ap-southeast-1.amazonaws.com/prod/ssl/prod-ca-2021.crt`.

To rotate access, replace `TRADES_API_KEY` in Vercel and redeploy. To disable the
database login, run `ALTER ROLE league_trades_api NOLOGIN` and terminate its
existing sessions. Secrets and David's ready-to-send instructions are kept in
ignored `data/private/trades-api/`; they must not be committed or uploaded.

Run `node --test scripts/tests/trades-api.test.cjs scripts/tests/trades-data.test.cjs`
and `pnpm build` before deploying.
Check a missing key returns 401, a valid key returns JSON with source counts, a
season filter works, and POST returns 405. Vercel filesystem routes must precede
the SPA fallback so `/api/trades` reaches the function and normal app pages work.
