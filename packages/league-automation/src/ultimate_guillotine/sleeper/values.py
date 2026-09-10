"""Two coercions every Sleeper payload needs.

Sleeper sends integers as strings in some places (``metadata.amount`` on a pick,
every season field) and as numbers in others, and stamps time as a millisecond
epoch that may be null. Both readings live here once so the draft and
transaction loaders agree on what a bad value is.
"""

from datetime import UTC, datetime


def as_int(value: object) -> int | None:
    """``53``, ``53.0`` and ``"53"`` all read as 53; a bool, a word, or nothing is None.

    A bool is excluded first because ``True`` is an ``int`` to Python and never one to
    Sleeper: a flag must not silently read as an amount of 1.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def from_millis(value: object) -> datetime | None:
    """A millisecond epoch as an aware UTC datetime; anything that is not a number is None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)
