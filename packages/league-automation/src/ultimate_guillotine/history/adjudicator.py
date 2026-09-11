"""Deterministic 2026 gulag transitions. Never use Sleeper head-to-head pairings."""

from dataclasses import dataclass
from decimal import Decimal

RULES_VERSION = "gulag-2026-v1"


class Unresolved(ValueError):
    """A required league fact or ruling is missing."""


@dataclass(frozen=True)
class Event:
    kind: str
    team: int
    reason: str | None = None
    opponent: int | None = None
    qualifier: int | None = None
    contest_week: int | None = None


@dataclass(frozen=True)
class Outcome:
    events: tuple[Event, ...]
    alive: tuple[int, ...]
    qualifiers: tuple[int, ...]


def expected_remaining(week: int) -> int:
    if not 1 <= week <= 17:
        raise Unresolved("week must be 1 through 17")
    return 18 if week == 1 else 19 - week if week < 12 else 18 - week


def bottom(
    scores: dict[int, Decimal], pool: set[int], count: int, tie_order: tuple[int, ...] = ()
) -> tuple[int, ...]:
    if len(pool) < count or not pool <= scores.keys():
        raise Unresolved("missing eligible team scores")
    ranked = sorted(pool, key=lambda t: (scores[t], t))
    if len(ranked) > count and scores[ranked[count - 1]] == scores[ranked[count]]:
        boundary = scores[ranked[count - 1]]
        tied = {t for t in pool if scores[t] == boundary}
        order = [t for t in tie_order if t in tied]
        if set(order) != tied or len(order) != len(tied):
            raise Unresolved("tied selection boundary needs an explicit ordered ruling")
        ranked = sorted(pool, key=lambda t: (scores[t], order.index(t) if t in tied else 0))
    return tuple(ranked[:count])


def adjudicate(
    week: int,
    alive: set[int],
    qualifiers: tuple[int, ...],
    scores: dict[int, Decimal],
    substitutions: dict[int, int] | None = None,
    tie_order: tuple[int, ...] = (),
) -> Outcome:
    expected_start = 18 if week == 1 else expected_remaining(week - 1)
    if len(alive) != expected_start:
        raise Unresolved(f"week {week} needs {expected_start} surviving teams")
    if not alive <= scores.keys() or any(not scores[t].is_finite() for t in alive):
        raise Unresolved("missing or non-finite score")
    substitutions = substitutions or {}
    events: list[Event] = []
    cuts: set[int] = set()
    participants: set[int] = set()
    if 2 <= week <= 12:
        if len(qualifiers) != 2 or len(set(qualifiers)) != 2 or not set(qualifiers) <= alive:
            raise Unresolved("previous week's finalized gulag qualifiers are required")
        if not substitutions.keys() <= set(qualifiers):
            raise Unresolved("substitution does not name an original qualifier")
        actual = {q: substitutions.get(q, q) for q in qualifiers}
        participants = set(actual.values())
        if len(participants) != 2 or not participants <= alive:
            raise Unresolved("gulag needs two distinct surviving participants")
        loser = bottom(scores, participants, 1, tie_order)[0]
        winner = next(t for t in participants if t != loser)
        for q, t in actual.items():
            events.append(Event("gulag_entered", t, qualifier=q, contest_week=week))
        events.append(
            Event(
                "gulag_survived",
                winner,
                opponent=loser,
                qualifier=next(q for q, t in actual.items() if t == winner),
                contest_week=week,
            )
        )
        events.append(
            Event(
                "eliminated",
                loser,
                "gulag_loss",
                winner,
                next(q for q, t in actual.items() if t == loser),
                week,
            )
        )
        cuts.add(loser)
    elif qualifiers or substitutions:
        raise Unresolved("this phase has no active gulag")

    next_qualifiers: tuple[int, ...] = ()
    # Select from the pre-transition pool. A gulag winner cannot immediately qualify again.
    pool = alive - participants
    if week <= 11:
        next_qualifiers = bottom(scores, pool, 2, tie_order)
        events.extend(
            Event("gulag_qualified", t, qualifier=t, contest_week=week + 1) for t in next_qualifiers
        )
    elif week <= 16:
        loser = bottom(scores, pool, 1, tie_order)[0]
        cuts.add(loser)
        events.append(Event("eliminated", loser, "direct_cut"))
    else:
        loser = bottom(scores, alive, 1, tie_order)[0]
        winner = next(t for t in alive if t != loser)
        cuts.add(loser)
        events.extend(
            (
                Event("eliminated", loser, "championship_loss", winner),
                Event("champion", winner, opponent=loser),
            )
        )
    remaining = alive - cuts
    if len(remaining) != expected_remaining(week):
        raise Unresolved("outcome does not match the season's cut count")
    return Outcome(tuple(events), tuple(sorted(remaining)), next_qualifiers)
