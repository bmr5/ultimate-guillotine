"""The survival model: how likely each team is to suffer this week's adverse event.

A deterministic Monte Carlo, pure standard library. Each simulation draws a
finish for every starter who can still score, adds it to what the team has
already put on the board, ranks the live teams, and applies the phase's rule --
the bottom two of the pool go down, the lower of the gulag pair goes out, the
lowest score is cut. The share of simulations in which a team suffers its event
is its odds.

**The numbers are estimates and the model says so.** Variance is a per-position
coefficient of variation with a floor, not a fitted distribution: a running back
projected for 15 is drawn from a normal with a standard deviation of 7.5,
truncated at zero. That is roughly the spread the position shows week to week and
it is deliberately simple, so the constants below are the whole model and a reader
can check any number by hand. The renderer rounds to whole percentages; nothing
here claims more precision than the inputs have.

**The seed comes from the inputs.** :func:`input_hash` digests the season, the
week, the phase, the gulag pairing and every team's score and starter statuses,
and the seed is the first sixteen hex digits of that digest. The same inputs
therefore always yield the same odds, and a stored snapshot can be replayed
exactly; ``--seed`` overrides it for a rehearsal.

Floats live inside this module and nowhere else: projections arrive as
``Decimal``, are converted at the draw, and the probabilities go back out as
``Decimal`` to four places.
"""

import hashlib
import json
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from ultimate_guillotine.summary.lineup import position_medians
from ultimate_guillotine.summary.models import (
    AdverseEvent,
    EodSnapshot,
    StarterLine,
    SurvivalResult,
    TeamOdds,
)

MODEL_VERSION = "mc-2026.1"
DEFAULT_SIMULATIONS = 10_000

#: A starter's standard deviation is this share of his projection, by position,
#: and never under :data:`SIGMA_FLOOR` points.
POSITION_CV: Mapping[str, float] = {
    "QB": 0.35,
    "RB": 0.50,
    "WR": 0.55,
    "TE": 0.60,
    "K": 0.55,
    "DEF": 0.60,
}
DEFAULT_CV = 0.50
SIGMA_FLOOR = 2.0
#: A starter whose game is under way has already resolved part of his week.
LIVE_SIGMA_SCALE = 0.6

_PROBABILITY = Decimal("0.0001")
_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class Draw:
    """What one pending starter adds: a mean, a spread, and whether the mean was a guess."""

    mean: Decimal
    sigma: float
    estimated: bool


def starter_draw(starter: StarterLine, medians: Mapping[str, Decimal]) -> Draw | None:
    """The draw for a starter who can still score, or ``None`` for one who cannot.

    A pending starter with no projection is drawn at his position's median and
    marked estimated; with no median either he counts for nothing, still marked.
    A ``live`` starter's mean is what his projection still has in it --
    ``max(0, projection - points so far)`` -- with a tighter spread.
    """
    if not starter.is_pending:
        return None
    projected = starter.projected
    estimated = projected is None
    if projected is None:
        projected = medians.get(starter.position or "")
        if projected is None:
            return Draw(Decimal(0), 0.0, True)
    cv = POSITION_CV.get(starter.position or "", DEFAULT_CV)
    sigma = max(SIGMA_FLOOR, cv * float(projected))
    mean = projected
    if starter.status == "live":
        mean = max(projected - starter.points, Decimal(0))
        sigma *= LIVE_SIGMA_SCALE
    return Draw(mean, sigma, estimated)


def input_hash(snapshot: EodSnapshot) -> str:
    """SHA-256 over everything the odds depend on, in a canonical order."""
    body = {
        "season": snapshot.season,
        "week": snapshot.week,
        "phase": snapshot.phase.kind,
        "gulag": sorted(snapshot.phase.gulag_team_ids),
        "teams": [
            {
                "id": team.team_id,
                "points": str(team.points),
                "eliminated": team.is_eliminated,
                "starters": [
                    {
                        "id": s.sleeper_player_id,
                        "status": s.status,
                        "position": s.position,
                        "projected": None if s.projected is None else str(s.projected),
                        "points": str(s.points),
                    }
                    for s in team.starters
                ],
            }
            for team in sorted(snapshot.teams, key=lambda t: t.team_id)
        ],
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _event_for(team_id: int, kind: str, gulag: Sequence[int]) -> AdverseEvent:
    if team_id in gulag:
        return "gulag_loss"
    if kind in ("entry", "gulag"):
        return "gulag_entry"
    if kind == "final":
        return "title_loss"
    return "cut"


def _bottom(totals: Mapping[int, float], ids: Sequence[int], count: int, rng: random.Random
            ) -> list[int]:
    """The lowest ``count`` of ``ids`` by total, ties broken at random."""
    if len(ids) < count:
        return []
    ranked = sorted(ids, key=lambda t: (totals[t], rng.random()))
    return ranked[:count]


def _losers(
    kind: str,
    totals: Mapping[int, float],
    gulag: Sequence[int],
    pool: Sequence[int],
    rng: random.Random,
) -> list[int]:
    """Who suffers the phase's event in one simulated week."""
    losers: list[int] = []
    if kind in ("gulag", "double") and gulag:
        losers.extend(_bottom(totals, gulag, 1, rng))
    if kind in ("entry", "gulag"):
        losers.extend(_bottom(totals, pool, 2, rng))
    elif kind in ("double", "cut", "final"):
        losers.extend(_bottom(totals, pool, 1, rng))
    return losers


def simulate(
    snapshot: EodSnapshot,
    *,
    simulations: int = DEFAULT_SIMULATIONS,
    seed: int | None = None,
) -> SurvivalResult | None:
    """Every live team's odds of this week's adverse event, or ``None`` after week 17.

    Eliminated teams are in no pool and get no entry. A gulag pairing that is not
    exactly two live teams is treated as no pairing: every live team is the pool
    and the event is entry to the gulag, which is what the message explains when
    the pairing is unknown.
    """
    phase = snapshot.phase
    if phase.kind == "over":
        return None
    digest = input_hash(snapshot)
    chosen_seed = seed if seed is not None else int(digest[:16], 16)
    rng = random.Random(chosen_seed)

    live = snapshot.live_teams()
    live_ids = [t.team_id for t in live]
    medians = position_medians(live)

    base: dict[int, float] = {}
    draws: dict[int, list[tuple[float, float]]] = {}
    means: dict[int, Decimal] = {}
    estimated: dict[int, bool] = {}
    pending: dict[int, int] = {}
    for team in live:
        base[team.team_id] = float(team.points)
        team_draws: list[tuple[float, float]] = []
        mean_total = team.points
        was_estimated = False
        left = 0
        for starter in team.starters:
            draw = starter_draw(starter, medians)
            if draw is None:
                continue
            left += 1
            mean_total += draw.mean
            was_estimated = was_estimated or draw.estimated
            team_draws.append((float(draw.mean), draw.sigma))
        draws[team.team_id] = team_draws
        means[team.team_id] = mean_total.quantize(_CENTS, rounding=ROUND_HALF_UP)
        estimated[team.team_id] = was_estimated
        pending[team.team_id] = left

    gulag = tuple(t for t in phase.gulag_team_ids if t in base)
    if len(gulag) != 2 or phase.kind not in ("gulag", "double"):
        gulag = ()
    pool = [t for t in live_ids if t not in gulag]

    counts = dict.fromkeys(live_ids, 0)
    gauss = rng.gauss
    for _ in range(simulations):
        totals: dict[int, float] = {}
        for team_id in live_ids:
            total = base[team_id]
            for mean, sigma in draws[team_id]:
                drawn = gauss(mean, sigma) if sigma > 0 else mean
                if drawn > 0:
                    total += drawn
            totals[team_id] = total
        for loser in _losers(phase.kind, totals, gulag, pool, rng):
            counts[loser] += 1

    teams = {
        team_id: TeamOdds(
            team_id=team_id,
            adverse_event=_event_for(team_id, phase.kind, gulag),
            probability=(Decimal(counts[team_id]) / Decimal(simulations)).quantize(
                _PROBABILITY, rounding=ROUND_HALF_UP
            ),
            projected_final=means[team_id],
            pending=pending[team_id],
            is_estimated=estimated[team_id],
        )
        for team_id in live_ids
    }
    return SurvivalResult(
        model_version=MODEL_VERSION,
        simulations=simulations,
        seed=chosen_seed,
        input_hash=digest,
        teams=teams,
    )
