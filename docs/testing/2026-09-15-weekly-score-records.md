# Historical weekly score records

Published to https://ultimate-guillotine-sage.vercel.app/history on September 15,
2026. Deployment `dpl_HoH3ULTCmRy8QY97HCTfbVpCToGQ`.

The History page now shows the five highest and lowest weekly scores, preserving
ties at the fifth rank. Each row names the manager, team, season, and week. Past
champion cards remain below the records.

## Sources and coverage

Imported 571 historical competitive team-week scores from these verified Sleeper
leagues, each named Ultimate Guillotine League and marked complete:

| Season | Sleeper league ID | Weeks | Scores |
| --- | --- | --- | --- |
| 2023 | 986707271361060864 | 1–17 | 197 |
| 2024 | 1119313867575783424 | 1–17 | 193 |
| 2025 | 1254581579569713152 | 1–17 | 181 |

2026 contributes the 18 confirmed Week 1 scores through the existing revisioned
archive. Later confirmations and corrections enter automatically; retracted and
provisional weeks are excluded. Coverage is visible on the page. No score archive
was located for 2019–2022, so the page explicitly says earlier seasons are missing.

The 2025 league was found through 2026's previous-league link. The commissioner's
public league list identified 2023 and 2024; 2024 also links back to 2023.
Matchup sources use `https://api.sleeper.app/v1/league/{league_id}/matchups/{week}`.
Public league-user metadata supplies historical team labels; existing public
member nicknames supply manager labels when identities match.

## Historical lineup exclusions

Sleeper retains entries after elimination. Some contain retired players and zero
points; others receive a keeper later, especially in Week 17. The historical
import infers a team's exit at its first cleared/one-player lineup or incomplete
all-zero placeholder lineup. Later scores for that roster remain excluded.
This is a historical participation inference, not a reconstruction of old rulings.

Partially filled competitive lineups remain eligible. Ben R's 22.50 in 2023 Week 7
has seven starters and real scoring and is retained. Full-lineup zero scores and
commissioner overrides remain valid. Scores are rounded to cents to remove
Sleeper's old floating-point artifacts. Weeks beyond 17 are excluded.

The available record high is Nick Nifty's 192.90 in 2024 Week 15. The record low
is Ben R's 22.50 in 2023 Week 7.

## Implementation and checks

- Migration `20260915190000_weekly_score_records.sql` adds the historical score
  table and an anonymous read-only record query. Current-season rows come from
  confirmed weekly roster snapshots, preserving the saved names.
- `scripts/import_weekly_score_history.py` is a dry run by default. `--apply`
  imports the reviewed historical leagues; it never writes Sleeper or sends messages.
- Four importer tests cover cleared rosters, later keeper receipts, placeholders,
  partial active lineups, real zeros, overrides, rounding, and invalid inputs.
- Seven database assertions passed in a rolled-back transaction, covering sorted
  extremes, ties, coverage, valid negative scores, and anonymous write restrictions.
- Six web tests passed for record display, coverage, loading/error states, current
  week links, and preservation of past champion cards. Build and lint passed.
- The public API returned 589 total competitive scores and the expected high/low.

The production upload contains only built website assets. Unrelated automation
edits in the shared checkout are excluded.

## Full-lineup low scores

Production deployment: `dpl_F5JBi1uLPf5nfZcAzCMCVUZMp1Hi`.

Added a third record list, **Lowest with full lineups**, on September 15. It ranks
only weeks with a distinct player in every required starting slot. Bench size is
irrelevant. Injured and bye-week players count as occupying a slot; the UI states
this explicitly. This filter does not infer a manager's intent to tank.

Migration `20260915200000_full_lineup_score_records.sql` stores historical filled
and required starting-slot counts. Unknown counts remain null and do not qualify.
The importer reads required slots from each historical league's roster settings,
excluding bench, IR, and taxi slots. Reimported all 571 historical records, finding
131 full lineups in 2023, 135 in 2024, and 131 in 2025. Current-season counts come
from the saved scoring lineup and the season's required starting positions.

The new low is Evan's 44.86 in 2023 Week 3. Ben R's 22.50 had seven filled starting
slots and remains only in the original lows. Verified that the existing highs,
lows, and coverage were identical before and after this change.

Six importer tests, six web tests, and six database assertions pass. Checks cover
empty slots, shortened arrays, duplicate players, unknown requirements, valid zero
scores, separate rankings and ties, and preservation of the existing lists.
Build and lint pass.

## Expand cards to the top ten

Production deployment: `dpl_Ax1CF7kroXExujvzxYCYi3ogHAUd`.

Each of the three cards initially shows the first five ranks. **Show top 10**
expands only that card; **Show less** collapses it. Ties at either boundary remain
visible. Controls expose their expanded state and associated list to assistive
technology, and expansion uses the already loaded results.

Migration `20260915210000_top_ten_score_records.sql` extends all three result lists
to rank ten. Verified that the original top-five records and coverage remain
unchanged. Eight web tests, nineteen database assertions, build, and lint pass.

## Full-lineup toggle

Production deployment: `dpl_JCcF1zNvsdoFmZAP8ehPVnjNmegD`.

The page now has two cards. **Full lineups only** is a switch inside **Lowest
weekly scores**, off by default. It selects the already loaded full-lineup records
and preserves the card's five/ten expansion state. The full-lineup definition
appears when enabled. The separate third card is removed.

Eight web tests, build, and lint pass, including switching the expanded low-score
card between both record sets and confirming that only two lists remain. This is
a website-only change; no database changes or historical reimport were needed.

## Click a score to see its roster

Production deployment: `dpl_6e5D6k4yeGi7W8DPwFW9R2JZ1cZp`.

Every score row opens a dialog with that team's saved lineup for the selected
week, player points, empty starting slots, and a separate bench table. Details
load when the dialog opens. The two cards, full-lineup toggle, and top-ten
expansion remain available. The current-season link is inside the dialog.

Migration `20260915220000_score_record_rosters.sql` adds sanitized historical
roster JSON and an anonymous read-only detail function keyed to the exact
season/week/team. Current-season details retain the confirmed-revision gates.
Historical starters and bench membership come from that week's Sleeper matchup;
player names come from the local directory with a Sleeper directory fallback.
Empty historical slots retain their positions. Current-season missing slots are
shown as generic starting slots because the existing archive reader omits their
original indices. Bench points do not contribute to the displayed team total.

All 571 historical records were backfilled. The record lists and coverage stayed
identical. Anonymous API checks covered all 22 distinct top-ten record entries
plus another confirmed 2026 result: each roster had named players and its starter
points matched the official total. Ben R's 22.50 shows seven filled slots, two
empty slots, and two bench players. Invalid record keys return null.

Eleven web tests, eight importer tests, five database assertions, the production
build, ESLint, and Ruff passed. Component checks cover opening/closing, lazy detail
loading, retry, missing records, zero points, empty slots, and bench separation.
Production HTTP checks verify the History page and assets against the built
files. No browser UI testing was performed.
