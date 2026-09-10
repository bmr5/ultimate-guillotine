"""The two coercions every Sleeper payload needs: an int that may arrive as a string,
and a millisecond epoch that may be missing."""

from datetime import UTC, datetime

from ultimate_guillotine.sleeper.values import as_int, from_millis


def test_an_int_is_read_from_an_int_a_float_or_a_numeric_string() -> None:
    assert as_int(53) == 53
    assert as_int(53.0) == 53
    assert as_int("53") == 53


def test_a_bool_a_word_and_nothing_are_not_ints() -> None:
    """`True` is an int to Python and never to Sleeper; a bool must not read as 1."""
    assert as_int(True) is None
    assert as_int("fifty") is None
    assert as_int(None) is None
    assert as_int([53]) is None


def test_a_millisecond_epoch_becomes_an_aware_utc_datetime() -> None:
    assert from_millis(1788822090433) == datetime(2026, 9, 7, 23, 1, 30, 433000, tzinfo=UTC)


def test_a_missing_or_unusable_epoch_is_none() -> None:
    assert from_millis(None) is None
    assert from_millis("1788822090433") is None
    assert from_millis(True) is None
