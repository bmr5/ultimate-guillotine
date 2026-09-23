"""10,000 reproducible league finishes using clock-scaled, fitted scoring distributions.

Offense uses a mean-preserving zero-inflated gamma. Defense uses signed normal
increments, including scoring declines. Historical full-game data fits dispersion;
linear remaining means and variance scaled by time are live-model assumptions.
"""

import hashlib
import json
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from ultimate_guillotine.summary.distributions import draw_points, parameters
from ultimate_guillotine.summary.lineup import position_medians
from ultimate_guillotine.summary.models import (
    AdverseEvent,
    EodSnapshot,
    StarterLine,
    SurvivalResult,
    TeamOdds,
)

MODEL_VERSION = "mc-2026.3"
DEFAULT_SIMULATIONS = 10_000

_PROBABILITY = Decimal("0.0001")
_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class Draw:
    mean: Decimal
    sigma: float
    estimated: bool
    position: str = "RB"
    zero_probability: float = 0


def starter_draw(
    starter: StarterLine, medians: Mapping[str, Decimal], model: dict | None = None
) -> Draw | None:
    if not starter.is_pending:
        return None
    model = model or parameters()
    projected = starter.projected
    estimated = projected is None
    if projected is None:
        projected = medians.get(starter.position or "")
        if projected is None:
            return Draw(Decimal(0), 0, True)
    if not projected.is_finite():
        raise ValueError("Nonfinite projection")
    position = starter.position or "RB"
    config = model["positions"].get(position, model["positions"]["RB"])
    fraction = Decimal(1)
    if starter.status == "live":
        fraction = starter.remaining_fraction
        if fraction is None or not fraction.is_finite() or not 0 <= fraction <= 1:
            raise ValueError("Missing or invalid live game clock")
    mu = projected * fraction
    if position == "DEF" and starter.status == "live":
        # Defense starts with points that can be lost. Project a signed change
        # toward the full-game expectation, converging to actual as time expires.
        mu = (projected - starter.points) * fraction
    sigma = (
        config["def_sigma"]
        if position == "DEF"
        else max(config["sigma_floor"], abs(float(projected)) * config["cv"])
    )
    sigma *= math.sqrt(float(fraction))
    zero = config["zero_probability"] ** float(fraction) if fraction else 0
    return Draw(mu, sigma, estimated, position, zero)


def input_hash(snapshot: EodSnapshot, model: dict | None = None) -> str:
    """SHA-256 over everything the odds depend on, in a canonical order."""
    body = {
        "model_version": MODEL_VERSION,
        "parameters": model or parameters(),
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
                        "remaining_fraction": str(s.remaining_fraction),
                    }
                    for s in team.projected_lineup()
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


def _bottom(
    totals: Mapping[int, float], ids: Sequence[int], count: int, rng: random.Random
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
    model: dict | None = None,
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
    if simulations < 1:
        raise ValueError("simulations must be positive")
    model = model or parameters()
    digest = input_hash(snapshot, model)
    chosen_seed = seed if seed is not None else int(digest[:16], 16)
    rng = random.Random(chosen_seed)

    live = snapshot.live_teams()
    live_ids = [t.team_id for t in live]
    medians = position_medians(live)

    base: dict[int, float] = {}
    draws: dict[int, list[Draw]] = {}
    means: dict[int, Decimal] = {}
    estimated: dict[int, bool] = {}
    pending: dict[int, int] = {}
    for team in live:
        base[team.team_id] = float(team.points)
        team_draws: list[Draw] = []
        mean_total = team.points
        was_estimated = False
        left = 0
        for starter in team.projected_lineup():
            draw = starter_draw(starter, medians, model)
            if draw is None:
                continue
            left += 1
            mean_total += draw.mean
            was_estimated = was_estimated or draw.estimated
            team_draws.append(draw)
        draws[team.team_id] = team_draws
        means[team.team_id] = mean_total.quantize(_CENTS, rounding=ROUND_HALF_UP)
        estimated[team.team_id] = was_estimated
        pending[team.team_id] = left

    gulag = tuple(t for t in phase.gulag_team_ids if t in base)
    if len(gulag) != 2 or phase.kind not in ("gulag", "double"):
        gulag = ()
    pool = [t for t in live_ids if t not in gulag]

    counts = dict.fromkeys(live_ids, 0)
    for _ in range(simulations):
        totals: dict[int, float] = {}
        for team_id in live_ids:
            total = base[team_id]
            for draw in draws[team_id]:
                total += draw_points(
                    rng, float(draw.mean), draw.sigma**2, draw.position, draw.zero_probability
                )
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
        model_parameters=model,
    )
