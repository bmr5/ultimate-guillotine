from enum import StrEnum

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DeliveryMode(StrEnum):
    DISABLED = "disabled"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: SecretStr
    sleeper_league_id: str = "1389372259260452864"
    delivery_mode: DeliveryMode = DeliveryMode.DISABLED
    test_chat_guid: str | None = None
    production_chat_guid: str | None = None
    production_participant_fingerprint: str | None = None
    bluebubbles_server_url: str = "http://127.0.0.1:1234"
    bluebubbles_password: SecretStr | None = None
    webhook_listen_host: str = "127.0.0.1"
    webhook_listen_port: int = 8646
    webhook_password: SecretStr | None = None
    hermes_profile_home: str = "~/.hermes/profiles/guillotine"
    discord_ops_channel: str = "#guillotine-ops"
    discord_feed_channel: str = "#guillotine-feed"
    discord_drafts_channel: str = "#guillotine-drafts"
    discord_alerts_channel: str = "#guillotine-alerts"
    hermes_model: str | None = None
    """Per-call model override for the structured-output client.

    Normally unset: the `guillotine` Hermes profile's `config.yaml` already names
    the model, and one place to change it beats two that can disagree.
    """

    @model_validator(mode="after")
    def validate_delivery_target(self) -> "Settings":
        if self.delivery_mode is DeliveryMode.TEST and not self.test_chat_guid:
            raise ValueError("test mode requires test_chat_guid")
        if self.delivery_mode is DeliveryMode.PRODUCTION and not (
            self.production_chat_guid and self.production_participant_fingerprint
        ):
            raise ValueError("production mode requires exact target identity")
        return self


def load_settings() -> Settings:
    return Settings()
