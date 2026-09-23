# Week 1 archive rehearsal

**Test only. Official standings and the public Current season page were not changed.**

Ran September 14, 2026 at 10:58 PM Central using fresh Sleeper scores and the existing week-close roster observation. All 16 NFL games were reported complete.

## Result

| Manager | Team | Week 1 score | Saved FAAB | Outcome |
| --- | --- | ---: | ---: | --- |
| Nick R | The Old Matt & the C (MC) | 59.60 | $79.00 | Qualifies for Week 2 gulag |
| Brandon L | SuperKing | 79.76 | $710.00 | Qualifies for Week 2 gulag |

**Official cuts: 0. Teams remaining: 18.**

## What the automation did

1. Captured fresh inputs in test scope and reused the saved week-close roster evidence.
2. Published a provisional Week 1 result with two gulag qualifications.
3. With the clock advanced to Tuesday 8:00 AM and the same inputs held unchanged, published the confirmed revision. This tests the confirmation path; it does not claim that Tuesday verification has already occurred.
4. Repeated the confirmed run. No duplicate revision appeared.
5. Rolled back every test database write and verified that official archive rows and elimination flags were unchanged.

The real scheduled run remains Monday at 11:30 PM Central, with confirmation Tuesday at 8:00 AM if the inputs meet the checks. No messages were sent.

## Saved rosters

Both snapshots use the September 14, 10:22 PM Central observation. The capture cadence met the worker's complete-coverage check. This is an observed cutoff, not an exact final-whistle timestamp. Player scoring comes from the fresh matchup data.

### Nick R: The Old Matt & the C (MC)

FAAB: **$79.00**. Saved player rows: **9**.

| Player | Position | Role | Points |
| --- | --- | --- | ---: |
| Christian McCaffrey | RB | Starter | 13.80 |
| Courtland Sutton | WR | Starter | 3.10 |
| Emmett Johnson | RB | Starter | 8.80 |
| Ja'Marr Chase | WR | Starter | 3.20 |
| Mark Andrews | TE | Starter | 8.90 |
| Matthew Stafford | QB | Starter | 5.10 |
| Quentin Johnston | WR | Starter | 3.70 |
| Tennessee Titans | DEF | Starter | 0.00 |
| Trey Smack | K | Starter | 13.00 |

### Brandon L: SuperKing

FAAB: **$710.00**. Saved player rows: **9**.

| Player | Position | Role | Points |
| --- | --- | --- | ---: |
| Alec Pierce | WR | Starter | 10.10 |
| Baltimore Ravens | DEF | Starter | 8.00 |
| Cam Skattebo | RB | Starter | 14.10 |
| Carnell Tate | WR | Starter | 7.80 |
| Eddy Pineiro | K | Starter | 11.00 |
| Jordan Addison | WR | Starter | 0.00 |
| Justin Herbert | QB | Starter | 14.26 |
| Tony Pollard | RB | Starter | 4.40 |
| Travis Kelce | TE | Starter | 10.10 |
