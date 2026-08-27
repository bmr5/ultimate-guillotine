# Game Pulse Agent

## Purpose

Automatically post concise after-game-window updates showing every active team's current position, remaining scoring opportunity, danger margin, and estimated survival odds.

This agent uses the shared design in `docs/superpowers/specs/2026-08-27-automation-foundation-design.md` and consumes provisional state from Weekly Adjudicator.

## Trigger and Cadence

Game Pulse runs only on days with NFL games relevant to the active scoring week:

- after the final Thursday game;
- after the final Sunday game;
- after the final Monday game.

The scheduler derives windows from the NFL schedule and waits for Sleeper scores to update after the scheduled end. A new post requires a materially newer score snapshot. Delayed or rescheduled games move the trigger rather than producing an incomplete fixed-time post.

## Inputs

- Current Sleeper matchup and roster snapshots.
- Active teams, current gulag, eliminated teams, and weekly rules phase.
- Player game status and remaining starters.
- Validated projection snapshot with at least 95 percent coverage of rostered unplayed starters.
- Current deterministic danger thresholds from Weekly Adjudicator.

## Survival Model

Survival odds are descriptive estimates, never official rulings. A deterministic Monte Carlo engine simulates remaining player outcomes from the normalized projection feed and ranks teams according to the active week's elimination rules.

Each run records:

- projection source and timestamp;
- score snapshot timestamp;
- model version and simulation count;
- team input values and result distribution;
- input hash for exact replay.

The model calculates the probability of the week's adverse result appropriate to the phase: entering the next gulag, losing the current gulag, receiving the Week 12 general-pool cut, or receiving a direct cut.

If projection coverage fails, the agent omits percentages and posts factual score rank, remaining players, and danger margin. Missing projections never become zero-point assumptions.

## Output

The message begins with the current danger line and groups teams into concise bands:

- immediate danger;
- live but vulnerable;
- strong position;
- finished and awaiting remaining games.

Each team line may include current points, players remaining, projected finish, and survival estimate. The footer includes `Estimates as of <time>` and the bot signature. The message avoids false precision by displaying whole percentages and marking volatile estimates when a small number of players dominate the result.

Monday's Game Pulse is explicitly provisional. Weekly Adjudicator owns the later final ruling.

## Deduplication

The unique publication identity is season, week, game window, score snapshot version, and model version. Repeated queue delivery with the same identity sends nothing. A corrected source may create a replacement only when ranking or displayed estimates change materially.

## Failure Behavior

- Projection outage or insufficient coverage: factual fallback without odds.
- Sleeper lag: wait and retry within the game-window job's bounded deadline.
- Incomplete roster mapping: omit the affected estimate, label the missing team, and alert the commissioner channel.
- AI outage: no effect on calculations; use the deterministic message renderer.
- Messages outage: retain the prepared recap for reconciliation and later send unless it has become stale.

A stale Game Pulse is not sent after a newer window or final weekly ruling exists.

## Test and Rollout

Tests cover active general-pool teams, current gulag teams, eliminated-team exclusion, no remaining players, a Monday player comeback, week-12 dual risk, direct-cut weeks, missing projections, postponed games, deterministic seeded simulation, and duplicate scheduled runs.

Self-test messages use anonymized teams and recorded projections before a live shadow week compares estimates with actual results. Production begins only after the projection coverage gate passes.

## Out of Scope

- Betting advice or financial wagering.
- Official rulings before Weekly Adjudicator finalizes.
- Fabricating odds without validated projections.

