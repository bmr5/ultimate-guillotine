from pydantic import BaseModel, ConfigDict, field_validator


class SleeperLeague(BaseModel, frozen=True):
    model_config = ConfigDict(extra="ignore")

    league_id: str
    name: str
    season: str
    total_rosters: int

    @property
    def season_year(self) -> int:
        """The season as a year, because Sleeper sends it as a string."""
        return int(self.season)


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
    starters: list[str] = []
    reserve: list[str] = []
    taxi: list[str] = []
    settings: dict[str, object] = {}
    metadata: dict[str, object] = {}

    @field_validator("players", "starters", "reserve", "taxi", mode="before")
    @classmethod
    def _no_players_is_an_empty_roster(cls, value: object) -> object:
        """Sleeper sends ``null`` for an empty list, not ``[]``."""
        return [] if value is None else value

    @field_validator("settings", "metadata", mode="before")
    @classmethod
    def _no_settings_is_an_empty_map(cls, value: object) -> object:
        """Sleeper sends ``null`` for an absent settings/metadata block, not ``{}``."""
        return {} if value is None else value
