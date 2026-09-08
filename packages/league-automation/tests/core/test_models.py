from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ultimate_guillotine.core.models import LeagueEvent, Season, Team


def test_season_defaults() -> None:
    season = Season(year=2026, sleeper_league_id="1389372259260452864")
    assert season.expected_rosters == 18
    assert season.rules_version == "2026.1"


def test_event_time_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        LeagueEvent(
            season=2026,
            event_type="trade",
            occurred_at=datetime(2026, 9, 1),  # noqa: DTZ001
            payload={},
        )
    LeagueEvent(season=2026, event_type="trade", occurred_at=datetime.now(UTC), payload={})


def test_models_are_frozen() -> None:
    team = Team(
        id=None,
        season=2026,
        member_id=1,
        sleeper_user_id="u1",
        sleeper_roster_id=3,
        team_name="Blades",
    )
    with pytest.raises(ValidationError):
        team.team_name = "Other"
