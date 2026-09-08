from pydantic import AwareDatetime, BaseModel


class Season(BaseModel, frozen=True):
    year: int
    sleeper_league_id: str
    expected_rosters: int = 18
    rules_version: str = "2026.1"


class Member(BaseModel, frozen=True):
    id: int | None
    display_name: str


class Team(BaseModel, frozen=True):
    id: int | None
    season: int
    member_id: int
    sleeper_user_id: str
    sleeper_roster_id: int
    team_name: str


class LeagueEvent(BaseModel, frozen=True):
    season: int
    week: int | None = None
    event_type: str
    occurred_at: AwareDatetime
    payload: dict[str, object]
    idempotency_key: str | None = None
