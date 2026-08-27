# Weekly Adjudicator Agent

## Purpose

Compute the official weekly league transition from Sleeper scores, prior league state, and accepted commissioner overrides. It automatically announces gulag entrants, gulag losers, direct cuts, survivors, and corrections.

This agent is deterministic and uses no language model for outcome selection. It uses the shared design in `docs/superpowers/specs/2026-08-27-automation-foundation-design.md`.

## Authoritative Rules

The 2026 rules are encoded as a versioned state machine:

- Week 1: no elimination; the bottom two eligible general-pool teams enter the Week 2 gulag.
- Weeks 2–11: the lower score among the current gulag participants is eliminated; the bottom two eligible general-pool teams enter the following week's gulag.
- Week 12: the Week 11 gulag loser and the lowest-scoring eligible general-pool team are eliminated.
- Weeks 13–16: the lowest-scoring remaining team is directly cut.
- Week 17: the final two determine the champion.

Current gulag teams are excluded when selecting new general-pool gulag entrants. Eliminated teams never reenter ranking. Ties, missing scores, score overrides, substitutions, and insurance exercises produce an unresolved state until a deterministic configured rule or accepted commissioner override resolves them.

## Inputs

- Active season and rules version.
- Sleeper league users, roster mapping, weekly matchups, and score snapshots.
- Prior finalized weekly state.
- Accepted gulag substitutions, insurance exercises, and commissioner score overrides.
- Team eligibility and elimination events.

Every computation stores an input hash so the same facts always produce the same result.

## Schedule

- Recompute provisional standings whenever a meaningful Sleeper score snapshot changes.
- After Monday's final game, queue a provisional adjudication post.
- Tuesday morning, recompute from a fresh Sleeper snapshot and finalize when scores have stabilized across two checks.
- Recheck later Tuesday for material stat corrections.

The exact run time follows the NFL schedule and Sleeper state rather than assuming every game window ends at a fixed wall-clock time.

## State Transition

The engine returns one of:

- `provisional`: games or score stabilization remain incomplete;
- `final`: all required inputs are available and the week transition is accepted;
- `unresolved`: an explicit tie, missing mapping, conflicting override, or rule edge case prevents a unique result;
- `corrected`: a later source version changes a finalized material outcome.

Only `final` and `corrected` states change official elimination or gulag membership. `unresolved` posts only to the commissioner channel and never guesses publicly.

## Output

The final message names:

- eliminated or cut team and score;
- surviving gulag team when applicable;
- new gulag entrants when applicable;
- relevant margin and next rule deadline;
- state version and signed bot identity.

Corrections explicitly name the prior outcome, corrected source fact, and new outcome. Cosmetic score changes that do not alter rank, gulag, cut, or winner do not create a league-chat correction.

## Overrides and Contracts

An insurance or champion substitution is a structured league event referencing the contract, buyer, substitute, covered week, cost, and acceptance evidence. It changes the gulag participant mapping but never overwrites original qualification history.

Commissioner overrides require an explicit authenticated operation or structured event. The Q&A agent cannot create them. Every override records actor, reason, source, and timestamp.

## Failure Behavior

- Missing roster mapping or duplicate Sleeper identity: enter `unresolved` and alert Ben directly.
- Sleeper outage: retain the prior snapshot, defer finalization, and retry.
- Stat correction after finalization: create a new state version and post only if materially different.
- Queue or Messages outage: preserve the final state and pending outbound job without recomputing a new decision.

## Test and Rollout

Tests replay synthetic seasons and retained historical scoring layouts across all 17 weeks. Required cases include week-one behavior, current-gulag exclusion, week-12 double elimination, direct-cut weeks, ties, missing scores, eliminated-team exclusion, substitution contracts, repeated runs, and material stat correction.

Production activation requires a full deterministic simulation from 18 teams to one champion and historical shadow runs that create no duplicate transitions.

## Out of Scope

- Judging collusion or discretionary penalties.
- Editing Sleeper scores or rosters.
- Using AI to resolve ties or rule ambiguity.

