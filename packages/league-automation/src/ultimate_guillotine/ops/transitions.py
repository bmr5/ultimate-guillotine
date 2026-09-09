"""One ops note per status change, not one per failed run.

A Sleeper outage lasts as long as it lasts, and a job that fires every five
minutes would otherwise post a wall of identical notes. The 5-minute
guillotine-health job already reports sustained staleness, so this module says
something only when the answer to "is it working?" actually changes.
"""

from datetime import datetime


def transition_note(
    agent: str, previous_status: str | None, current_status: str, now: datetime
) -> str | None:
    """Return the note to post, or None when nothing changed worth saying."""
    stamp = f"{now:%Y-%m-%d %H:%M} UTC"
    if current_status == "failed" and previous_status != "failed":
        return f"{agent}: run failed at {stamp}"
    if current_status == "succeeded" and previous_status == "failed":
        return f"{agent}: recovered at {stamp}"
    return None
