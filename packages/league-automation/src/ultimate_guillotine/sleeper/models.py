from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, field_validator


class SleeperLeague(BaseModel, frozen=True):
    model_config = ConfigDict(extra="ignore")

    league_id: str
    name: str
    season: str
    total_rosters: int
    scoring_settings: dict[str, object] = {}
    roster_positions: list[str] = []
    settings: dict[str, object] = {}
    #: The league's canonical draft. Listing ``/league/{id}/drafts`` is the wrong key: the
    #: 2025 league also carries an abandoned one-pick draft.
    draft_id: str | None = None

    @property
    def season_year(self) -> int:
        """The season as a year, because Sleeper sends it as a string."""
        return int(self.season)

    @property
    def waiver_budget(self) -> int | None:
        """The league's FAAB budget, or None when Sleeper is not running one."""
        value = self.settings.get("waiver_budget")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return int(value)


class SleeperUser(BaseModel, frozen=True):
    model_config = ConfigDict(extra="ignore")

    user_id: str
    display_name: str
    username: str = ""
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


class SleeperDraft(BaseModel, frozen=True):
    """The draft record behind ``league.draft_id``: its kind, its status, its dimensions."""

    model_config = ConfigDict(extra="ignore")

    draft_id: str
    type: str
    status: str
    start_time: int | None = None
    last_picked: int | None = None
    settings: dict[str, object] = {}

    @field_validator("settings", mode="before")
    @classmethod
    def _no_settings_is_an_empty_map(cls, value: object) -> object:
        return {} if value is None else value

    def _setting(self, key: str) -> int | None:
        value = self.settings.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return int(value)

    @property
    def teams(self) -> int | None:
        return self._setting("teams")

    @property
    def rounds(self) -> int | None:
        return self._setting("rounds")

    @property
    def started_at(self) -> datetime | None:
        """When the draft opened, from Sleeper's millisecond epoch.

        Falls back to ``last_picked`` when Sleeper never stamped a start, so a
        completed draft always has a date for the journey's first entry.
        """
        millis = self.start_time if self.start_time is not None else self.last_picked
        if millis is None:
            return None
        return datetime.fromtimestamp(millis / 1000, tz=UTC)
