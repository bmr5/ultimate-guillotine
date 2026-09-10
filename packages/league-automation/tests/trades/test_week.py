from datetime import UTC, date, datetime

from ultimate_guillotine.sleeper.state import NflState
from ultimate_guillotine.trades.week import LAST_WEEK, week_for


def state(**overrides) -> NflState:
    base = {
        "season": 2026,
        "season_type": "regular",
        "week": 3,
        "display_week": 3,
        "leg": 3,
        "previous_season": 2025,
        "season_start_date": date(2026, 9, 3),
        "raw": {},
        "synced_at": datetime(2026, 9, 10, tzinfo=UTC),
    }
    base.update(overrides)
    return NflState(**base)


def test_the_week_is_counted_from_the_season_start() -> None:
    assert week_for(datetime(2026, 9, 3, 12, tzinfo=UTC), state()) == 1
    assert week_for(datetime(2026, 9, 9, 23, 59, tzinfo=UTC), state()) == 1
    assert week_for(datetime(2026, 9, 10, 0, 1, tzinfo=UTC), state()) == 2
    assert week_for(datetime(2026, 10, 15, tzinfo=UTC), state()) == 7


def test_before_the_start_is_week_one_and_late_is_clamped() -> None:
    assert week_for(datetime(2026, 8, 20, tzinfo=UTC), state()) == 1
    assert week_for(datetime(2027, 2, 1, tzinfo=UTC), state()) == LAST_WEEK


def test_without_a_start_date_the_current_week_stands_in() -> None:
    assert week_for(datetime(2026, 9, 10, tzinfo=UTC), state(season_start_date=None, week=5)) == 5


def test_without_a_state_row_there_is_no_answer() -> None:
    assert week_for(datetime(2026, 9, 10, tzinfo=UTC), None) is None
