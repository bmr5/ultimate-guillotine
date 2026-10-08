from unittest.mock import Mock

import pytest

from ultimate_guillotine.cli.odds import require_prior_week_confirmed


def connection_with_archive_status(status):
    conn = Mock()
    conn.execute.return_value.fetchone.return_value = None if status is None else (status,)
    return conn


@pytest.mark.parametrize("status", ["pending", "provisional", "unresolved"])
def test_odds_stop_when_the_prior_week_is_not_finalized(status):
    conn = connection_with_archive_status(status)

    with pytest.raises(ValueError, match="Week 2 elimination state is not finalized"):
        require_prior_week_confirmed(conn, season_id=1, week=3)


def test_odds_continue_after_the_prior_week_is_confirmed():
    conn = connection_with_archive_status("confirmed")

    require_prior_week_confirmed(conn, season_id=1, week=3)


def test_odds_continue_when_the_archive_is_not_enabled():
    conn = connection_with_archive_status(None)

    require_prior_week_confirmed(conn, season_id=1, week=3)


def test_week_one_does_not_query_for_a_prior_week():
    conn = Mock()

    require_prior_week_confirmed(conn, season_id=1, week=1)

    conn.execute.assert_not_called()
