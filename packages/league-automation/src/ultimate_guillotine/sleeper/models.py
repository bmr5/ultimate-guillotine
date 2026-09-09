from pydantic import BaseModel, ConfigDict, field_validator


class SleeperLeague(BaseModel, frozen=True):
    model_config = ConfigDict(extra="ignore")

    league_id: str
    name: str
    season: str
    total_rosters: int


class SleeperUser(BaseModel, frozen=True):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    display_name: str
    metadata: dict[str, object] = {}

    @property
    def team_name(self) -> str:
        """The user's configured team name, or their display name."""
        value = self.metadata.get("team_name")
        return value if isinstance(value, str) and value else self.display_name


class SleeperRoster(BaseModel, frozen=True):
    model_config = ConfigDict(extra="ignore")

    roster_id: int
    owner_id: str
    players: list[str] = []

    @field_validator("players", mode="before")
    @classmethod
    def _no_players_is_an_empty_roster(cls, value: object) -> object:
        """Sleeper sends ``"players": null`` for an empty roster, not ``[]``."""
        return [] if value is None else value
