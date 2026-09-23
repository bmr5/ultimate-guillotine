# Weekly scores and rosters

Published September 15, 2026 to the existing league website at
https://ultimate-guillotine-sage.vercel.app/current-season?week=1.
Vercel deployment: `dpl_FUKLNu68CWGZkKRPNDqan95hGYzr`.

Current season opens to **Scores & rosters**. The week selector keeps its choice
when switching to **Gulag & cuts**. Teams appear by descending official score,
with tied scores sharing a rank. Expanding a team shows its saved players,
starter/bench roles, individual points, and the observed roster cutoff in Central
time. Zero points and missing points remain distinct. Weeks awaiting confirmation
and withdrawn results show an explanation instead of live scores.

## Archive reads

Applied `20260915180000_weekly_roster_browser.sql` and recorded it in the hosted
database's migration history. Its read-only `get_weekly_rosters` function accepts
only the current confirmed production revision. It returns an explicit allowlist
of team and player fields without granting browser access to private observations.

Team totals come from the latest official weekly results. Rosters and names come
from the published event revision's pinned cutoff observation. Player scoring
comes from the last production capture at or before confirmation, with each
matchup checked against its official team total. Later captures cannot substitute
today's roster or unconfirmed scoring changes. Corrections load under their new
revision ID. Old and test revision IDs return no rows, as does a confirmed revision
superseded by a retraction.

## Validation

- All 14 database assertions passed inside a rolled-back transaction, covering
  correction selection, pinned rosters, starter order, departed players, missing
  points, private fields, test scopes, and retraction behavior.
- All 28 focused web tests passed, including existing page/navigation tests and
  new week-switching, ranking, roster, request, and error-state checks.
- Production build and lint passed. The existing large-bundle advisory remains.
- The public API returned 18 Week 1 teams and 162 saved player rows. The leader's
  score is 164.06 and the roster cutoff is September 14 at 10:22 PM Central.
- Released only the built static website. Existing automation source edits in
  the shared checkout were not included in the upload.
