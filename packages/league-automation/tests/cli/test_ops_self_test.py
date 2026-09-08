"""`ug ops self-test` must be re-runnable and reconcilable.

Gate 0 check 4 forces a crash between send and record, then re-runs the self-test
within the same minute and expects `reconciled`. That only works if two things hold
at once: the content is identical across the two attempts (so the content hash
matches the reservation left behind), and the idempotency key differs (so the retry
is not swallowed as a duplicate run).
"""

import re
from datetime import UTC, datetime

import pytest

from ultimate_guillotine.cli import ops as ops_module
from ultimate_guillotine.config import DeliveryMode, Settings

# Two moments in the same minute: the crashed attempt and the retry.
FIRST = datetime(2026, 9, 8, 23, 47, 12, 345678, tzinfo=UTC)
RETRY = datetime(2026, 9, 8, 23, 47, 58, 999999, tzinfo=UTC)


class FakeDelivery:
    def __init__(self, recorder):
        self._recorder = recorder

    def deliver(self, run_id, agent, content):
        self._recorder.append(content)
        return type("R", (), {"status": "sent", "outbound_id": 1})()


class FakeDeps:
    def __init__(self, settings):
        self.settings = settings
        self.conn = object()
        self.client = object()
        self.notifier = object()


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch):
    """Drive `cmd_self_test` over fakes, returning the clock, the delivered contents,
    and the (agent, trigger, idempotency_key) triples handed to `run_scheduled`."""
    settings = Settings(
        database_url="postgresql://x:y@example.invalid/db",
        delivery_mode=DeliveryMode.TEST,
        test_chat_guid="iMessage;+;chat-test",
        _env_file=None,
    )
    clock = [FIRST]
    contents: list[str] = []
    scheduled: list[tuple] = []

    class FrozenDatetime:
        @staticmethod
        def now(tz):
            return clock[0]

    def fake_run_scheduled(conn, agent, now, action, trigger="cron", idempotency_key=None):
        scheduled.append((agent, trigger, idempotency_key))
        return action(1)

    monkeypatch.setattr(ops_module, "datetime", FrozenDatetime)
    monkeypatch.setattr(ops_module, "build_deps", lambda: FakeDeps(settings))
    monkeypatch.setattr(
        ops_module, "build_delivery", lambda deps, crash_after_send=False: FakeDelivery(contents)
    )
    monkeypatch.setattr(ops_module, "run_scheduled", fake_run_scheduled)
    return clock, contents, scheduled


def _args():
    return type("Args", (), {"crash_after_send": False})()


def test_self_test_content_is_minute_precise(harness) -> None:
    _clock, contents, _scheduled = harness
    assert ops_module.cmd_self_test(_args()) == 0
    assert contents == ["Self-test 2026-09-08T23:47"]
    assert re.fullmatch(r"Self-test \d{4}-\d{2}-\d{2}T\d{2}:\d{2}", contents[0])


def test_retry_in_the_same_minute_repeats_content_but_not_the_run_key(harness) -> None:
    clock, contents, scheduled = harness
    ops_module.cmd_self_test(_args())
    clock[0] = RETRY
    ops_module.cmd_self_test(_args())

    # Same content, so the retry's hash matches the reservation the crash left behind.
    assert contents == ["Self-test 2026-09-08T23:47"] * 2

    assert {agent for agent, _, _ in scheduled} == {"self-test"}
    assert {trigger for _, trigger, _ in scheduled} == {"cli"}
    keys = [key for _, _, key in scheduled]
    assert keys == ["self-test:20260908T234712345678", "self-test:20260908T234758999999"]
