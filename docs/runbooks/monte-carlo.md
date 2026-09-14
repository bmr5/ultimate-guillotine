# Monte Carlo forecasts

Model `mc-2026.2` uses 10,000 simulated league finishes. The existing score job
runs `ug odds refresh --quiet` after each successful score sync: every minute in
Thursday/Sunday/Monday game windows, every five minutes otherwise. The board
checks for new odds every 15 seconds and labels odds awaiting refresh after ten
minutes. Neither the live refresh nor evaluation sends messages.

## Scoring model

Sleeper projections remain the expected full-game scores, scored with this
league's settings. For offense, remaining expectation is projection times the
fraction of the game remaining. Remaining variance is full-game variance times
that fraction. At the final whistle the simulation uses actual points only.
ESPN supplies game clocks, including halftime and overtime. A missing live clock,
unmatched lineup, stale score feed, or insufficient projection coverage withholds
new odds. A changed scoring-settings fingerprint requires a new fit.

Offense uses zero-inflated gamma draws. This adds busts and a right tail for
breakout games while preserving the requested mean and variance, without clipping
normal draws and accidentally raising their average. Offensive future scoring is
modeled as nonnegative; future fumble deductions are not explicitly simulated.
Defense uses signed normal changes. A live defense's expected change is
`(full-game projection - actual) * fraction remaining`, allowing its current
score to fall. The board uses that same defense expectation.

Players are drawn independently. Game correlations, possession, usage changes,
and in-game injury probabilities are not fitted. Linear time scaling is an
assumption, not a live model validated against play-by-play history.

## Historical check

`distribution_parameters.json` records the scoring settings, source fingerprint,
sample sizes, fit parameters and holdout metrics. Fit: 2024 regular weeks 1–17.
Check: 2025 regular weeks 1–17. This week's outcomes were not used for fitting.
The fit includes projected QB scores >=5, RB/WR/TE >=3, K/DEF >=1, with matched
actual rows; absent actual rows are excluded rather than assumed zero.

| Position | 2025 samples | Old 80% interval coverage | New coverage | Old CRPS | New CRPS |
| --- | ---: | ---: | ---: | ---: | ---: |
| QB | 512 | 66.8% | 77.3% | 4.430 | 4.368 |
| RB | 1,045 | 67.5% | 83.3% | 3.675 | 3.674 |
| WR | 1,635 | 65.3% | 89.1% | 3.661 | 3.583 |
| TE | 715 | 70.3% | 89.7% | 3.234 | 3.201 |
| K | 503 | 81.5% | 82.7% | 2.594 | 2.595 |
| DEF | 512 | 61.7% | 81.1% | 3.565 | 3.445 |

Lower CRPS is better and penalizes overly broad predictions as well as misses.
The kicker difference is negligible; WR/TE intervals are too broad at this level.
These are retrospective checks: Sleeper can revise historical projections after
kickoff, so this is not a clean prospective backtest or proof of calibrated league
cut odds. Individual historical player weeks are not independent league outcomes.

Refit a candidate without replacing the deployed model automatically:

```sh
uv run --project packages/league-automation ug odds train \
  --cache /tmp/ug-mc-history --out /tmp/candidate-mc-parameters.json
```

## Replay and evaluation

Every new `survival_snapshots.inputs` stores the full lineup, actual scores,
projections, player status, time remaining, phase/pairing, source timestamps,
scoring settings, distribution parameters, model version, and exact random seed.
Older forecasts keep null inputs; their original inputs cannot be recovered from
a hash. Use the matching code version when replaying an old model.

```sh
uv run --project packages/league-automation ug odds refresh --dry-run
uv run --project packages/league-automation ug odds replay SNAPSHOT_ID
uv run --project packages/league-automation ug odds evaluate \
  --out data/private/monte-carlo-evaluation.json
```

The archive tick refreshes that local evaluation report after its final-result
work. Each model/week contributes only its earliest forecast in each horizon,
with pregame and in-game cohorts separate. Evaluation waits for a complete set of
final scores, excludes ambiguous tied cutoffs and unresolved gulag pairings, and
reports Brier score, point MAE, reliability bins, lineup changes, and an unchanged
lineup score separately. Subsequent final-score corrections are picked up on the
next evaluation. The source snapshots remain unchanged.

The report can be empty until a week is finalized. Multiple ticks from one game
must never be counted as hundreds of independent forecast successes. Assess
calibration across multiple weeks, and compare the same forecast horizon.
