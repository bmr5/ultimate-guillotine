from datetime import UTC, datetime

from ultimate_guillotine.ops.transitions import transition_note

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def test_one_note_on_the_transition_into_failure() -> None:
    note = transition_note("projections-sync", "succeeded", "failed", NOW)
    assert note == "projections-sync: run failed at 2026-09-09 12:00 UTC"


def test_consecutive_failures_are_silent() -> None:
    assert transition_note("projections-sync", "failed", "failed", NOW) is None


def test_one_note_on_recovery() -> None:
    note = transition_note("projections-sync", "failed", "succeeded", NOW)
    assert note == "projections-sync: recovered at 2026-09-09 12:00 UTC"


def test_steady_success_and_a_first_ever_failure_are_handled() -> None:
    assert transition_note("nfl-state", "succeeded", "succeeded", NOW) is None
    assert transition_note("nfl-state", None, "failed", NOW) is not None
    assert transition_note("nfl-state", None, "succeeded", NOW) is None
