# Trade Registrar case results

Run 2026-09-10 04:19 UTC against the fake client (harness self-check).
Cases come from `packages/league-automation/tests/fixtures/registrar_cases.json`;
case text is deliberately not repeated here.

Two kinds of case are skipped rather than run, and neither counts as a failure:
one that needs a prior case already on file, which a dry run cannot produce, and
one marked `dropped_upstream`, which the listener discards before the agent is
reached at all. Asking the model about a message it never sees in production would
score an answer nothing depends on.

**74 run · 74 passed · 0 failed · 14 skipped (prerequisite state) · 1 dropped upstream.**

| # | category | expected kind | expected status | actual kind | outcome | result | mismatch |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | happy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 2 | happy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 3 | happy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 4 | happy | `rental` | `created` | `rental` | `created` | pass | — |
| 5 | happy | `payment` | `created` | `payment` | `created` | pass | — |
| 6 | happy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 7 | happy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 8 | happy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 9 | happy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 10 | happy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 11 | happy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 12 | happy | `rental` | `created` | `rental` | `created` | pass | — |
| 13 | happy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 14 | happy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 15 | happy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 16 | happy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 17 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 18 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 19 | sloppy | `permanent` | `clarification` | `permanent` | `clarification` | pass | — |
| 20 | sloppy | `permanent` | `clarification` | `permanent` | `clarification` | pass | — |
| 21 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 22 | sloppy | `permanent` | `clarification` | `permanent` | `clarification` | pass | — |
| 23 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 24 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 25 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 26 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 27 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 28 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 29 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 30 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 31 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 32 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 33 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 34 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 35 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 36 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 51 | not_a_trade | `not_a_trade` | `not_a_trade` | `not_a_trade` | `not_a_trade` | pass | — |
| 52 | not_a_trade | `not_a_trade` | `not_a_trade` | `not_a_trade` | `not_a_trade` | pass | — |
| 53 | not_a_trade | `not_a_trade` | `not_a_trade` | `not_a_trade` | `not_a_trade` | pass | — |
| 54 | not_a_trade | `not_a_trade` | `not_a_trade` | `not_a_trade` | `not_a_trade` | pass | — |
| 56 | not_a_trade | `not_a_trade` | `not_a_trade` | `not_a_trade` | `not_a_trade` | pass | — |
| 57 | happy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 58 | not_a_trade | `not_a_trade` | `not_a_trade` | `not_a_trade` | `not_a_trade` | pass | — |
| 59 | unclear | `unclear` | `clarification` | `unclear` | `clarification` | pass | — |
| 60 | unclear | `unclear` | `clarification` | `unclear` | `clarification` | pass | — |
| 61 | unclear | `unclear` | `clarification` | `unclear` | `clarification` | pass | — |
| 62 | unclear | `rental` | `clarification` | `rental` | `clarification` | pass | — |
| 63 | unclear | `unclear` | `clarification` | `unclear` | `clarification` | pass | — |
| 64 | privacy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 65 | privacy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 66 | privacy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 67 | privacy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 68 | privacy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 69 | scale | `permanent` | `created` | `permanent` | `created` | pass | — |
| 70 | scale | `permanent` | `created` | `permanent` | `created` | pass | — |
| 71 | scale | `permanent` | `created` | `permanent` | `created` | pass | — |
| 72 | scale | `permanent` | `created` | `permanent` | `created` | pass | — |
| 73 | unclear | `unclear` | `clarification` | `unclear` | `clarification` | pass | — |
| 74 | happy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 75 | unclear | `unclear` | `clarification` | `unclear` | `clarification` | pass | — |
| 76 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 77 | unclear | `unclear` | `clarification` | `unclear` | `clarification` | pass | — |
| 78 | rescission | `rescission` | `clarification` | `rescission` | `clarification` | pass | — |
| 79 | happy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 80 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 81 | sloppy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 82 | unclear | `permanent` | `clarification` | `permanent` | `clarification` | pass | — |
| 83 | unclear | `unclear` | `clarification` | `unclear` | `clarification` | pass | — |
| 84 | happy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 85 | happy | `permanent` | `created` | `permanent` | `created` | pass | — |
| 86 | happy | `rental` | `created` | `rental` | `created` | pass | — |
| 87 | not_a_trade | `not_a_trade` | `not_a_trade` | `not_a_trade` | `not_a_trade` | pass | — |
| 88 | not_a_trade | `not_a_trade` | `not_a_trade` | `not_a_trade` | `not_a_trade` | pass | — |
| 89 | not_a_trade | `not_a_trade` | `not_a_trade` | `not_a_trade` | `not_a_trade` | pass | — |

## Totals by category

| category | run | passed | failed |
| --- | --- | --- | --- |
| happy | 22 | 22 | 0 |
| sloppy | 23 | 23 | 0 |
| not_a_trade | 9 | 9 | 0 |
| unclear | 10 | 10 | 0 |
| privacy | 5 | 5 | 0 |
| scale | 4 | 4 | 0 |
| rescission | 1 | 1 | 0 |

## Skipped

These cases need a prior case already on file, which a dry run has no way to
produce: 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50.

## Dropped upstream

The listener drops these before the trigger runs -- the bot's own signed text --
so they never reach extraction and are skipped by design: 55.
