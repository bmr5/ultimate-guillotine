import pytest

from ultimate_guillotine.sleeper.models import SleeperLeague
from ultimate_guillotine.sleeper.sync import validate_league


def test_validate_rejects_wrong_roster_count() -> None:
    league = SleeperLeague(league_id="1389372259260452864", name="Ultimate Guillotine League", season="2026", total_rosters=12)
    with pytest.raises(ValueError, match="expected 18 rosters"):
        validate_league(league, expected_id="1389372259260452864", expected_rosters=18)


def test_validate_rejects_wrong_id() -> None:
    league = SleeperLeague(league_id="1", name="Ultimate Guillotine League", season="2026", total_rosters=18)
    with pytest.raises(ValueError, match="league id"):
        validate_league(league, expected_id="1389372259260452864", expected_rosters=18)


def test_validate_accepts_matching_league() -> None:
    league = SleeperLeague(league_id="1389372259260452864", name="Ultimate Guillotine League", season="2026", total_rosters=18)
    validate_league(league, expected_id="1389372259260452864", expected_rosters=18)
