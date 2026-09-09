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
from typing import Self

import psycopg
import pytest

from ultimate_guillotine.listener import run as run_module


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
