"""`Settings` validation.

Every construction here passes `_env_file=None`. `Settings` reads `.env` from the
working directory by default, and both the repository root and the Mac mini have a
real one, so without this the suite would silently validate the developer's live
configuration instead of the values under test.
"""

import pytest
from pydantic import ValidationError

from ultimate_guillotine.config import DeliveryMode, Settings

BASE = {
    "database_url": "postgresql://worker:secret@example.invalid/postgres",
    "_env_file": None,
}


def test_production_requires_exact_target_identity() -> None:
    with pytest.raises(ValidationError):
        Settings(
            **BASE,
            delivery_mode=DeliveryMode.PRODUCTION,
            test_chat_guid="iMessage;+;chat-test",
        )


def test_test_mode_requires_test_chat() -> None:
    with pytest.raises(ValidationError):
        Settings(**BASE, delivery_mode=DeliveryMode.TEST)


def test_disabled_needs_no_targets() -> None:
    settings = Settings(**BASE)
    assert settings.delivery_mode is DeliveryMode.DISABLED
    assert settings.webhook_listen_host == "127.0.0.1"


def test_secrets_do_not_repr() -> None:
    settings = Settings(**BASE, bluebubbles_password="hunter2")
    assert "hunter2" not in repr(settings)


def test_model_settings_default_to_the_hermes_profile() -> None:
    """No model key and no model id of its own: the `guillotine` Hermes profile
    holds both, and `hermes_model` only overrides the model when it is set."""
    settings = Settings(**BASE)
    assert settings.hermes_profile_home == "~/.hermes/profiles/guillotine"
    assert settings.hermes_model is None
    assert not hasattr(settings, "openrouter_api_key")


def test_a_model_override_is_read_when_it_is_set() -> None:
    assert Settings(**BASE, hermes_model="gpt-5.6-sol").hermes_model == "gpt-5.6-sol"
