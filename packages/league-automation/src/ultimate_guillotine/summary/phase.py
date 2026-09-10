"""The rules phase: what this week's adverse event is, and who is in the gulag.

The week table is the season simulation in
``docs/rules/ultimate-guillotine-gulag-league-rules.docx``: week 1 sends its bottom
two into the week 2 gulag; weeks 2 to 11 eliminate the gulag loser and send the
next bottom two down; week 12 takes the gulag loser and the lowest of the rest;
weeks 13 to 16 cut the lowest score outright; week 17 is the final.

**Who is in the gulag is read, never decided, here.** The Weekly Adjudicator's
``gulag_entry`` rows in ``public.league_events`` are the ruling when they exist.
Until they do, the pairing is *replayed* from the stored scores: each week's
bottom two of the pool -- the live teams less that week's gulag -- form the next
week's gulag. The replay cannot see a score correction, a commissioner override,
or a member paying somebody else to take their place, which the rules allow, so it
is labelled ``replay`` and the message calls it provisional. A past week with no
scores on file makes the pairing ``unknown`` rather than a guess.
"""

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal

from ultimate_guillotine.summary.models import GulagSource, Phase, PhaseKind

#: The first week that eliminates the gulag loser, and the last such week.
FIRST_GULAG_WEEK = 2
LAST_GULAG_WEEK = 12
#: The championship week: the last two teams play, and the league is decided.
FINAL_WEEK = 17
#: How many teams a gulag holds.
GULAG_SIZE = 2


def phase_kind(week: int) -> PhaseKind:
    if week <= 1:
        return "entry"
    if week < LAST_GULAG_WEEK:
        return "gulag"
    if week == LAST_GULAG_WEEK:
        return "double"
    if week < FINAL_WEEK:
        return "cut"
    if week == FINAL_WEEK:
        return "final"
    return "over"


def has_gulag(kind: PhaseKind) -> bool:
    return kind in ("gulag", "double")


def gulag_from_events(
    events: Iterable[tuple[int | None, str, Mapping[str, object]]], week: int
) -> tuple[int, ...] | None:
    """The pair the Adjudicator ruled into this week's gulag, or ``None``.

    ``events`` are ``(week, event_type, payload)`` rows. Exactly two ``gulag_entry``
    rows for the week, each naming an integer ``team_id``, make a pairing; anything
    less is half a ruling and the caller falls back to the replay.
    """
    ids: set[int] = set()
    for event_week, event_type, payload in events:
        if event_week != week or event_type != "gulag_entry":
            continue
        team_id = payload.get("team_id") if isinstance(payload, Mapping) else None
        if isinstance(team_id, bool) or not isinstance(team_id, int):
            continue
        ids.add(team_id)
    if len(ids) != GULAG_SIZE:
        return None
    return tuple(sorted(ids))


def _bottom(
    scores: Mapping[int, Decimal], pool: Iterable[int], count: int
) -> tuple[int, ...] | None:
    """The lowest ``count`` scores in ``pool``; ties by team id; ``None`` if too few."""
    ranked = sorted((scores[t], t) for t in pool if t in scores)
    if len(ranked) < count:
        return None
    return tuple(sorted(t for _points, t in ranked[:count]))


def replay_gulag(
    week: int,
    scores_by_week: Mapping[int, Mapping[int, Decimal]],
    eliminated: Mapping[int, int | None],
    team_ids: Sequence[int],
) -> tuple[int, ...] | None:
    """This week's gulag pair, replayed from every earlier week's scores.

    ``eliminated`` maps each eliminated team to the week it went out, ``None`` when
    that was never recorded. A team is alive in a replayed week when it is not
    eliminated or went out in that week or later -- the gulag loser of week 3 was on
    the field in week 3. A team with no recorded week is left out of every replayed
    week: it cannot be placed, and guessing a pairing around it is worse than a
    pool one team smaller.

    Returns ``None`` when a needed week has no scores, or too few, on file.
    """
    if week < FIRST_GULAG_WEEK or week > LAST_GULAG_WEEK:
        return None

    def alive_in(replay_week: int) -> list[int]:
        return [
            t
            for t in team_ids
            if t not in eliminated or (eliminated[t] is not None and eliminated[t] >= replay_week)
        ]

    gulag: tuple[int, ...] = ()
    for replay_week in range(1, week):
        scores = scores_by_week.get(replay_week)
        if not scores:
            return None
        pool = [t for t in alive_in(replay_week) if t not in gulag]
        entrants = _bottom(scores, pool, GULAG_SIZE)
        if entrants is None:
            return None
        gulag = entrants
    return gulag


def resolve_phase(
    week: int,
    events: Iterable[tuple[int | None, str, Mapping[str, object]]],
    scores_by_week: Mapping[int, Mapping[int, Decimal]],
    eliminated: Mapping[int, int | None],
    team_ids: Sequence[int],
) -> Phase:
    """The phase for ``week``: its kind, and its gulag pair with the pair's provenance."""
    kind = phase_kind(week)
    if not has_gulag(kind):
        return Phase(week=week, kind=kind, gulag_team_ids=(), gulag_source="none")
    ruled = gulag_from_events(events, week)
    if ruled is not None:
        return Phase(week=week, kind=kind, gulag_team_ids=ruled, gulag_source="events")
    replayed = replay_gulag(week, scores_by_week, eliminated, team_ids)
    source: GulagSource = "unknown" if replayed is None else "replay"
    return Phase(week=week, kind=kind, gulag_team_ids=replayed or (), gulag_source=source)
