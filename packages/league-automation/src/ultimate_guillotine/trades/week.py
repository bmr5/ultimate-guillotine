"""The NFL week a trade alert belongs to, read off the clock rather than the model.

Ben (2026-09-10): "The week should be very easily determined by the exact day
the trade was created." An alert almost never states its week, and the model
was leaving the field empty, so the registrar was posting `Week ?`. The week is
a property of *when* the alert was sent: the state sync keeps Sleeper's
``season_start_date`` and current ``week``, and those settle it in code.
"""

from __future__ import annotations

from datetime import datetime

from ultimate_guillotine.sleeper.state import NflState

__all__ = ["FIRST_WEEK", "LAST_WEEK", "week_for"]

FIRST_WEEK = 1
#: Sleeper's regular season runs eighteen weeks; the guillotine ends with it.
LAST_WEEK = 18


def week_for(sent_at: datetime, state: NflState | None) -> int | None:
    """The week containing ``sent_at``.

    Counted in seven-day steps from Sleeper's ``season_start_date`` when the
    state row carries one, clamped to the regular season; a message before the
    start belongs to week 1. Without a start date the row's own ``week`` stands
    in (it is "the week we are in", which is right for every live alert). With
    no state row at all there is no answer, and the caller decides.
    """
    if state is None:
        return None
    if state.season_start_date is not None:
        days = (sent_at.date() - state.season_start_date).days
        if days < 0:
            return FIRST_WEEK
        return min(LAST_WEEK, days // 7 + FIRST_WEEK)
    return state.week if state.week else None
