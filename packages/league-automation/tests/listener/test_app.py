import json
import os
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from ultimate_guillotine.listener.app import create_app

FIXTURE = Path(__file__).parent.parent / "fixtures" / "bluebubbles" / "new_message.json"


class ExitCalled(Exception):
    """Stands in for the process death `os._exit` would cause."""


class DeadHeartbeats:
    def beat(self, component):
        raise psycopg.OperationalError("connection to server was lost")


@pytest.fixture
def exit_codes(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    codes: list[int] = []

    def fake_exit(code: int) -> None:
        codes.append(code)
        raise ExitCalled

    monkeypatch.setattr(os, "_exit", fake_exit)
    return codes


class FakeProcessor:
    def __init__(self):
        self.calls = []

    def process(self, msg, event_id):
        self.calls.append((msg.guid, event_id))
        return "no_trigger"


class FakeHeartbeats:
    def __init__(self):
        self.beats = 0

    def beat(self, component):
        self.beats += 1


def test_rejects_wrong_password() -> None:
    processor, beats = FakeProcessor(), FakeHeartbeats()
    client = TestClient(create_app(processor, beats, "secret"))
    response = client.post(
        "/bluebubbles-webhook?password=nope", json=json.loads(FIXTURE.read_text())
    )
    assert response.status_code == 401
    # Rejection happens before anything is read or written: an unauthenticated caller
    # can neither drive a trigger nor fake a listener heartbeat.
    assert processor.calls == []
    assert beats.beats == 0


def test_processes_new_message_and_beats() -> None:
    processor, beats = FakeProcessor(), FakeHeartbeats()
    client = TestClient(create_app(processor, beats, "secret"))
    response = client.post(
        "/bluebubbles-webhook?password=secret", json=json.loads(FIXTURE.read_text())
    )
    assert response.status_code == 200
    assert response.json() == {"outcome": "no_trigger"}
    assert processor.calls == [("p:0/ABC", "p:0/ABC")]
    assert beats.beats == 1


def test_healthz_is_ok_without_a_database_check() -> None:
    client = TestClient(create_app(FakeProcessor(), FakeHeartbeats(), "secret"))
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_healthz_is_ok_when_the_database_check_passes() -> None:
    client = TestClient(
        create_app(FakeProcessor(), FakeHeartbeats(), "secret", check_db=lambda: True)
    )
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_healthz_is_unavailable_when_the_database_check_fails() -> None:
    """`ug ops doctor` and launchd both read /healthz; a listener whose connection is
    gone is not healthy just because its HTTP server still answers."""
    client = TestClient(
        create_app(FakeProcessor(), FakeHeartbeats(), "secret", check_db=lambda: False)
    )
    response = client.get("/healthz")
    assert response.status_code == 503


def test_webhook_exits_when_the_database_connection_is_dead(
    exit_codes: list[int], caplog: pytest.LogCaptureFixture
) -> None:
    """A listener holding a dead connection can never recover on its own; exiting
    non-zero hands it to launchd's KeepAlive, which restarts it with a fresh one."""
    client = TestClient(create_app(FakeProcessor(), DeadHeartbeats(), "secret"))
    with pytest.raises(ExitCalled):
        client.post(
            "/bluebubbles-webhook?password=secret", json=json.loads(FIXTURE.read_text())
        )
    assert exit_codes == [1]
    assert "OperationalError" in caplog.text
    assert "connection to server was lost" not in caplog.text


def test_healthz_exits_when_the_database_connection_is_dead(exit_codes: list[int]) -> None:
    def dead_check() -> bool:
        raise psycopg.OperationalError("connection to server was lost")

    client = TestClient(
        create_app(FakeProcessor(), FakeHeartbeats(), "secret", check_db=dead_check)
    )
    with pytest.raises(ExitCalled):
        client.get("/healthz")
    assert exit_codes == [1]


def test_non_message_events_are_acknowledged() -> None:
    processor = FakeProcessor()
    client = TestClient(create_app(processor, FakeHeartbeats(), "secret"))
    response = client.post(
        "/bluebubbles-webhook?password=secret", json={"type": "hello-world", "data": {}}
    )
    assert response.json() == {"outcome": "ignored_event"}
    assert processor.calls == []
