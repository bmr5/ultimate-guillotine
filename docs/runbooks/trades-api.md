# Trades API

`GET https://ultimate-guillotine-sage.vercel.app/api/trades` returns registered
trades with their current revisions, the historical trade catalog, and a manager
ID directory. Optional `?season=2026` filters both trade sources. Without the
filter, all available seasons are returned. Rescinded registrations are retained;
`TEST-` trade codes are excluded. The two sources can overlap and must not be
counted as unique trades by simply adding their lengths.

Send the secret in `X-API-Key` or `Authorization: Bearer ...`. Keys in URLs are not
accepted. Responses use `Cache-Control: private, no-store`. Only GET is supported.
No private schema, source-message GUID, administrator key or database connection
string is returned. Registered terms include the league's original announcement.

Server-only production environment variables:

- `TRADES_API_KEY`: randomly generated, separately revocable client credential.
- `TRADES_DATABASE_URL`: dedicated `league_trades_api` session-pooler login with
  SELECT on `trades`, `trade_revisions`, `trade_catalog`, `seasons`, and `members`.
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

Run `node --test scripts/tests/trades-api.test.cjs` and `pnpm build` before deploying.
Check a missing key returns 401, a valid key returns JSON with source counts, a
season filter works, and POST returns 405. Vercel filesystem routes must precede
the SPA fallback so `/api/trades` reaches the function and normal app pages work.
