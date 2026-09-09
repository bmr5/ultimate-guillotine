"""Tests for `cli.deps`'s `run_scheduled` and `build_deps`, using fakes (no database)."""

from datetime import UTC, datetime

import pytest

from ultimate_guillotine.ai.hermes import HermesStructuredClient
from ultimate_guillotine.cli import deps as deps_module
from ultimate_guillotine.cli.deps import Deps, build_ai, build_deps, run_scheduled
from ultimate_guillotine.config import Settings

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


class FakeConn:
    def __init__(self, reserve_result: int | None) -> None:
        self.reserve_result = reserve_result
        self.reserve_calls = 0
        self.reserve_args: list[tuple[str, str, str]] = []
        self.finish_calls: list[tuple[int, str, str | None]] = []
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class FakeRunRepository:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    def reserve(
        self, agent: str, trigger: str, idempotency_key: str, invoked_by: str | None = None
    ) -> int | None:
        self._conn.reserve_calls += 1
        self._conn.reserve_args.append((agent, trigger, idempotency_key))
        return self._conn.reserve_result

    def finish(
        self,
        run_id: int,
        status: str,
        output_hash: str | None = None,
        error: str | None = None,
    ) -> None:
        self._conn.finish_calls.append((run_id, status, error))


@pytest.fixture(autouse=True)
def _fake_run_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps_module, "RunRepository", FakeRunRepository)


def test_run_scheduled_success_reserves_finishes_succeeded_and_commits() -> None:
    conn = FakeConn(reserve_result=7)

    result = run_scheduled(conn, "health", NOW, lambda run_id: 0)

    assert result == 0
    assert conn.reserve_calls == 1
    assert conn.finish_calls == [(7, "succeeded", None)]
    assert conn.commits == 1


def test_run_scheduled_reraises_and_finishes_failed_on_exception() -> None:
    conn = FakeConn(reserve_result=9)

    class BoomError(Exception):
        pass

    def action(run_id: int) -> int:
        raise BoomError("kaboom")

    with pytest.raises(BoomError):
        run_scheduled(conn, "health", NOW, action)

    assert conn.reserve_calls == 1
    assert conn.finish_calls == [(9, "failed", "BoomError")]
    assert conn.commits == 1


def test_run_scheduled_skips_action_when_reserve_returns_none() -> None:
    conn = FakeConn(reserve_result=None)
    called = False

    def action(run_id: int) -> int:
        nonlocal called
        called = True
        return 0

    result = run_scheduled(conn, "health", NOW, action)

    assert result is None
    assert called is False
    assert conn.finish_calls == []
    assert conn.commits == 0


def test_build_deps_propagates_connect_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class BoomError(Exception):
        pass

    def boom(settings: object) -> None:
        raise BoomError("no route to host")

    monkeypatch.setattr(deps_module, "load_settings", lambda: object())
    monkeypatch.setattr(deps_module, "connect", boom)

    with pytest.raises(BoomError):
        build_deps()


def test_run_scheduled_defaults_to_one_cron_key_per_agent_per_minute() -> None:
    conn = FakeConn(reserve_result=7)

    run_scheduled(conn, "health", NOW, lambda run_id: 0)

    assert conn.reserve_args == [("health", "cron", "health:20260908T1200")]


def test_run_scheduled_forwards_an_explicit_trigger_and_key() -> None:
    """The self-test is re-run by hand inside the same minute during Gate 0, so it
    supplies a per-attempt key rather than sharing the per-minute cron one."""
    conn = FakeConn(reserve_result=7)

    run_scheduled(
        conn,
        "self-test",
        NOW,
        lambda run_id: 0,
        trigger="cli",
        idempotency_key="self-test:20260908T120000123456",
    )

    assert conn.reserve_args == [
        ("self-test", "cli", "self-test:20260908T120000123456")
    ]


def _deps(**overrides) -> Deps:
    settings = Settings(
        database_url="postgresql://x:y@example.invalid/db", _env_file=None, **overrides
    )
    return Deps(settings=settings, conn=None, client=None, notifier=None)


def test_build_ai_exits_when_the_hermes_cli_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The credentials live in the Hermes profile, so the CLI is the only thing
    that can be missing -- and a plain message beats a subprocess traceback."""
    monkeypatch.setattr(deps_module, "find_hermes_binary", lambda: None)
    with pytest.raises(SystemExit) as exc_info:
        build_ai(_deps())
    assert "hermes CLI not found" in str(exc_info.value)


def test_build_ai_points_the_client_at_the_profile_and_the_model_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps_module, "find_hermes_binary", lambda: "/bin/hermes")
    client = build_ai(_deps(hermes_profile_home="/tmp/profile", hermes_model="gpt-5.6-sol"))
    assert isinstance(client, HermesStructuredClient)
    assert client._home == "/tmp/profile"
    assert client._model == "gpt-5.6-sol"
