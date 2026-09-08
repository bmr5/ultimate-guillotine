"""The listener's background heartbeat.

The webhook-driven beat alone made a quiet chat indistinguishable from a dead
listener, so the health job alerted every night. These tests drive the loop
directly; `main()` starts it as a daemon thread and nothing else does.
"""

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


def test_heartbeat_loop_beats_on_the_configured_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps = _patched_sleep(monkeypatch, stop_after=2)
    beats: list[str] = []

    class FakeHeartbeats:
        def beat(self, component: str) -> None:
            beats.append(component)

    with pytest.raises(StopLoop):
        run_module._heartbeat_loop(FakeHeartbeats())

    assert beats == ["listener", "listener"]
    assert sleeps == [run_module.HEARTBEAT_INTERVAL_SECONDS] * 2


def test_heartbeat_loop_survives_a_failed_beat_and_logs_only_the_class_name(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sleeps = _patched_sleep(monkeypatch, stop_after=2)
    beats: list[str] = []

    class FakeHeartbeats:
        def beat(self, component: str) -> None:
            beats.append(component)
            if len(beats) == 1:
                raise RuntimeError("password=hunter2 host=secret.invalid")

    with pytest.raises(StopLoop):
        run_module._heartbeat_loop(FakeHeartbeats())

    # The first beat blew up; the loop kept going rather than killing the thread.
    assert beats == ["listener", "listener"]
    assert len(sleeps) == 2
    assert "RuntimeError" in caplog.text
    assert "hunter2" not in caplog.text
    assert "secret.invalid" not in caplog.text
