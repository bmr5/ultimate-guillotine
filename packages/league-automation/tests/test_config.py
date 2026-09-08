import pytest
from pydantic import ValidationError

from ultimate_guillotine.config import DeliveryMode, Settings

BASE = {"database_url": "postgresql://worker:secret@example.invalid/postgres"}


def test_production_requires_exact_target_identity() -> None:
    with pytest.raises(ValidationError):
        Settings(**BASE, delivery_mode=DeliveryMode.PRODUCTION, test_chat_guid="iMessage;+;chat-test")


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
