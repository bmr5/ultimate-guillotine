"""The listener's background heartbeat and database health probe.

The webhook-driven beat alone made a quiet chat indistinguishable from a dead
listener, so the health job alerted every night. These tests drive the loop and the
probe directly; `main()` wires them into real connections and nothing else does.

The heartbeat thread and the `/healthz` probe each open their own connection rather
than sharing the request-path connection: a `/healthz` rollback on a shared
connection could otherwise discard another thread's uncommitted work between its
`reserve` and `commit`.
"""

import os
from datetime import UTC, datetime
from typing import Self

import psycopg
import pytest

from ultimate_guillotine.config import Settings
from ultimate_guillotine.listener import run as run_module
from ultimate_guillotine.messages.bluebubbles import InboundMessage


class StopLoop(Exception):
    """Breaks the otherwise infinite heartbeat loop from the patched sleep."""


def _patched_sleep(monkeypatch, stop_after: int) -> list[float]:
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == stop_after:
            raise StopLoop

    monkeypatch.setattr(run_module, "sleep", fake_sleep)
    return sleeps


class FakeCursor:
    """Stands in for a psycopg cursor, recording each execute's params."""

    def __init__(self, on_execute):
        self._on_execute = on_execute

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql, params=None) -> None:
        self._on_execute(params)


class FakeConnection:
    """Stands in for a psycopg connection, recording commits and rollbacks."""

    def __init__(self, on_execute=None):
        self.commits = 0
        self.rollbacks = 0
        self._on_execute = on_execute or (lambda params: None)

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._on_execute)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class DeadConnection:
    """A connection whose first use raises, as a dropped database link would."""

    def cursor(self):
        raise psycopg.OperationalError("connection to server was lost")

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


def test_heartbeat_loop_beats_on_the_configured_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps = _patched_sleep(monkeypatch, stop_after=2)
    beats: list[tuple] = []
    conn = FakeConnection(on_execute=lambda params: beats.append(params))

    with pytest.raises(StopLoop):
        run_module._heartbeat_loop(lambda: conn)

    assert beats == [("listener",), ("listener",)]
    assert sleeps == [run_module.HEARTBEAT_INTERVAL_SECONDS] * 2
    assert conn.commits == 2


def test_heartbeat_loop_survives_a_failed_beat_and_logs_only_the_class_name(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sleeps = _patched_sleep(monkeypatch, stop_after=2)
    calls = {"count": 0}

    def on_execute(params) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("password=hunter2 host=secret.invalid")

    conn = FakeConnection(on_execute=on_execute)

    with pytest.raises(StopLoop):
        run_module._heartbeat_loop(lambda: conn)

    # The first beat blew up; the loop kept going rather than killing the thread.
    assert calls["count"] == 2
    assert len(sleeps) == 2
    assert "RuntimeError" in caplog.text
    assert "hunter2" not in caplog.text
    assert "secret.invalid" not in caplog.text
    assert conn.rollbacks == 1
    assert conn.commits == 1


def test_heartbeat_loop_opens_its_own_connection_via_the_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loop must use the connection its factory returns, not a request connection
    handed to it some other way -- it never sees one at all."""
    _patched_sleep(monkeypatch, stop_after=1)
    created: list[FakeConnection] = []

    def factory() -> FakeConnection:
        conn = FakeConnection()
        created.append(conn)
        return conn

    with pytest.raises(StopLoop):
        run_module._heartbeat_loop(factory)

    assert len(created) == 1
    assert created[0].commits == 1


def test_heartbeat_loop_exits_the_process_on_a_lost_connection(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class ExitCalled(Exception):
        """Stands in for the process death `os._exit` would cause."""

    def fake_exit(code: int) -> None:
        raise ExitCalled(code)

    monkeypatch.setattr(os, "_exit", fake_exit)
    _patched_sleep(monkeypatch, stop_after=5)  # the loop must never reach sleep

    with pytest.raises(ExitCalled) as exc_info:
        run_module._heartbeat_loop(lambda: DeadConnection())

    assert exc_info.value.args == (1,)
    assert "OperationalError" in caplog.text
    assert "connection to server was lost" not in caplog.text


def test_heartbeat_loop_exits_when_the_connection_cannot_be_opened(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class ExitCalled(Exception):
        """Stands in for the process death `os._exit` would cause."""

    def fake_exit(code: int) -> None:
        raise ExitCalled(code)

    def factory():
        raise psycopg.OperationalError(
            "connection to server was lost"
        )

    monkeypatch.setattr(os, "_exit", fake_exit)
    _patched_sleep(monkeypatch, stop_after=5)  # must never reach sleep

    with pytest.raises(ExitCalled) as exc_info:
        run_module._heartbeat_loop(factory)

    assert exc_info.value.args == (1,)
    assert "OperationalError" in caplog.text
    assert "connection to server was lost" not in caplog.text


class FakeProbe:
    """Stands in for the context-managed connection `check_db` probes with."""

    def __init__(self, on_execute=None):
        self._on_execute = on_execute or (lambda sql: None)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql) -> None:
        self._on_execute(sql)


def test_check_db_returns_false_when_the_factory_raises_operational_error() -> None:
    def factory():
        raise psycopg.OperationalError("connection to server was lost")

    assert run_module._check_db(factory) is False


def test_check_db_returns_true_when_the_probe_succeeds() -> None:
    assert run_module._check_db(lambda: FakeProbe()) is True


def test_check_db_never_touches_a_connection_it_did_not_open() -> None:
    request_conn = FakeConnection()

    result = run_module._check_db(lambda: FakeProbe())

    assert result is True
    assert request_conn.commits == 0
    assert request_conn.rollbacks == 0


class EmptyCursor:
    """A cursor whose every query comes back empty, as an unconfigured database would."""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql, params=None) -> None:
        pass

    def fetchone(self):
        return None

    def fetchall(self) -> list:
        return []


class EmptyConnection:
    """A connection that answers `build_processor`'s target lookups with nothing."""

    def cursor(self) -> EmptyCursor:
        return EmptyCursor()

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


class RecordingNotifier:
    """Records the ops notes `build_processor` posts at startup."""

    def __init__(self) -> None:
        self.ops_sent: list[str] = []

    def ops(self, text: str) -> bool:
        self.ops_sent.append(text)
        return True


def _settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql://x:y@example.invalid/db",
        "delivery_mode": "test",
        "test_chat_guid": "iMessage;+;chat-test",
        "_env_file": None,
    }
    return Settings(**{**base, **overrides})


def _registry_names(processor) -> list[str]:
    return [t.name for t in processor._registry._triggers]


@pytest.fixture
def hermes_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The registrar shells out to the hermes CLI, which a test machine may lack."""
    monkeypatch.setattr(run_module, "find_hermes_binary", lambda: "/bin/hermes")


def test_build_processor_registers_the_trade_registrar_with_a_chat_and_the_cli(
    hermes_installed: None,
) -> None:
    notifier = RecordingNotifier()

    processor, _allowed = run_module.build_processor(
        _settings(), EmptyConnection(), None, None, notifier
    )

    assert "trade-registrar" in _registry_names(processor)
    assert "trade-advisor" in _registry_names(processor)
    assert notifier.ops_sent == []


def test_build_processor_announces_the_registrar_is_disabled_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No hermes CLI means no model call at all, so the listener starts without
    the registrar and says so once rather than failing every alert."""
    monkeypatch.setattr(run_module, "find_hermes_binary", lambda: None)
    notifier = RecordingNotifier()

    processor, _allowed = run_module.build_processor(
        _settings(), EmptyConnection(), None, None, notifier
    )

    assert "trade-registrar" not in _registry_names(processor)
    assert "trade-advisor" not in _registry_names(processor)
    assert notifier.ops_sent == [
        "Trade Registrar disabled: hermes CLI not found",
        "Trade Advisor disabled: hermes CLI not found",
    ]


def _alert(chat_guid: str) -> InboundMessage:
    return InboundMessage(
        guid="g1", chat_guid=chat_guid, sender_address="+15555550100",
        text="🚨 Member01 sends Player Alpha to Member02", is_from_me=False, is_group=True,
        sent_at=datetime.now(UTC),
    )


def _trade_trigger(processor):
    return next(t for t in processor._registry._triggers if t.name == "trade-registrar")


def test_the_registrar_trigger_is_gated_on_the_delivery_chat(hermes_installed: None) -> None:
    """A listener that can see more than one chat must answer trades in one."""
    processor, _allowed = run_module.build_processor(
        _settings(), EmptyConnection(), None, None, RecordingNotifier(),
    )

    trigger = _trade_trigger(processor)

    assert trigger.matches(_alert("iMessage;+;chat-test"))
    assert not trigger.matches(_alert("iMessage;+;chat-elsewhere"))


def test_build_processor_skips_the_registrar_when_no_chat_is_configured(
    hermes_installed: None,
) -> None:
    notifier = RecordingNotifier()

    processor, _allowed = run_module.build_processor(
        _settings(delivery_mode="disabled", test_chat_guid=None),
        EmptyConnection(), None, None, notifier,
    )

    assert "trade-registrar" not in _registry_names(processor)
    assert notifier.ops_sent == ["Trade Registrar disabled: no target chat for disabled"]


def test_the_advisor_answers_in_the_self_test_chat_and_only_there() -> None:
    """The spec keeps the Advisor in the self-test chat until Ben promotes it."""
    assert run_module.advisor_chat_guid(_settings()) == "iMessage;+;chat-test"


def test_the_advisor_never_registers_in_production(
    hermes_installed: None, caplog: pytest.LogCaptureFixture
) -> None:
    """Production is a deliberate, reviewed change to `advisor_chat_guid`, not a
    database row somebody adds -- and it is a log line, not an ops note, because
    it is the expected state of every production start rather than a fault."""
    caplog.set_level("INFO")
    settings = _settings(
        delivery_mode="production", production_chat_guid="prod",
        production_participant_fingerprint="fp", test_chat_guid=None,
    )
    notifier = RecordingNotifier()

    assert run_module.advisor_chat_guid(settings) is None
    processor, _allowed = run_module.build_processor(
        settings, EmptyConnection(), None, None, notifier
    )

    assert "trade-advisor" not in _registry_names(processor)
    assert not [note for note in notifier.ops_sent if "Advisor" in note]
    assert "trade advisor disabled" in caplog.text.lower()


def _advice_request(chat_guid: str) -> InboundMessage:
    return InboundMessage(
        guid="g2", chat_guid=chat_guid, sender_address="+15555550100",
        text="@bot who should I trade with for a RB", is_from_me=False, is_group=True,
        sent_at=datetime.now(UTC),
    )


def test_the_advisor_trigger_is_gated_on_the_delivery_chat(hermes_installed: None) -> None:
    processor, _allowed = run_module.build_processor(
        _settings(), EmptyConnection(), None, None, RecordingNotifier(),
    )

    trigger = next(t for t in processor._registry._triggers if t.name == "trade-advisor")

    assert trigger.matches(_advice_request("iMessage;+;chat-test"))
    assert not trigger.matches(_advice_request("iMessage;+;chat-elsewhere"))
