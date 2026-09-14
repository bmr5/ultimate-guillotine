from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ultimate_guillotine.ops import recovery

NOW = datetime(2026, 9, 14, 14, tzinfo=UTC)


@pytest.fixture
def local_app(monkeypatch, tmp_path):
    monkeypatch.setattr(recovery.sys, "platform", "darwin")
    monkeypatch.setattr(recovery, "BLUEBUBBLES_APP", tmp_path)


def test_stopped_app_is_opened_once_and_verified(local_app):
    client = Mock()
    client.ping.side_effect = [False, False, True]
    runner = Mock(side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)])
    state, save = {}, Mock()
    note = recovery.recover_bluebubbles(
        client, "http://127.0.0.1:1234", state, save, NOW, runner=runner, sleep=Mock()
    )
    assert "connection verified" in note
    assert runner.call_count == 2
    assert runner.call_args_list[1].args[0][:4] == ["/usr/bin/open", "-g", "-j", "-a"]
    save.assert_called_once()
    assert "bluebubbles" not in state


@pytest.mark.parametrize("returncode", [0, 2])
def test_running_app_or_failed_process_check_never_relaunches(local_app, returncode):
    runner = Mock(return_value=SimpleNamespace(returncode=returncode))
    recovery.recover_bluebubbles(
        Mock(ping=lambda: False),
        "http://localhost:1234",
        {},
        Mock(),
        NOW,
        runner=runner,
        sleep=Mock(),
    )
    assert runner.call_count == 1


def test_remote_endpoint_never_launches_local_app(local_app):
    runner = Mock()
    recovery.recover_bluebubbles(
        Mock(ping=lambda: False), "https://example.com", {}, Mock(), NOW, runner=runner
    )
    runner.assert_not_called()


def test_retry_budget_survives_processes_and_has_cooldown(local_app, tmp_path):
    runner = Mock(
        side_effect=lambda *a, **kw: SimpleNamespace(
            returncode=1 if a[0][0].endswith("pgrep") else 0
        )
    )

    def attempt(now):
        with recovery.health_state(tmp_path) as (state, save):
            return recovery.recover_bluebubbles(
                Mock(ping=lambda: False),
                "http://localhost:1234",
                state,
                save,
                now,
                runner=runner,
                sleep=Mock(),
            )

    attempt(NOW)
    attempt(NOW + timedelta(minutes=5))
    assert runner.call_count == 2
    attempt(NOW + timedelta(minutes=15))
    attempt(NOW + timedelta(minutes=30))
    assert runner.call_count == 6
    assert "stopped after 3 attempts" in attempt(NOW + timedelta(minutes=45))
    assert runner.call_count == 6


def test_healthy_ping_resets_retry_budget(local_app):
    state = {"bluebubbles": {"attempts": 3}}
    runner = Mock()
    recovery.recover_bluebubbles(
        Mock(ping=lambda: True), "http://localhost:1234", state, Mock(), NOW, runner=runner
    )
    assert "bluebubbles" not in state
    runner.assert_not_called()


def test_launch_failure_is_counted(local_app):
    state = {}
    note = recovery.recover_bluebubbles(
        Mock(ping=lambda: False),
        "http://localhost:1234",
        state,
        Mock(),
        NOW,
        runner=Mock(return_value=SimpleNamespace(returncode=1)),
        sleep=Mock(),
    )
    assert "launch failed" in note
    assert state["bluebubbles"]["attempts"] == 1


def test_alerts_ignore_new_failure_timestamps_and_report_recovery_once():
    state, send = {}, Mock(return_value=True)
    recovery.report_changes(["gap-fill: last run failed at 2026-09-14 13:48 UTC"], state, send)
    recovery.report_changes(["gap-fill: last run failed at 2026-09-14 13:52 UTC"], state, send)
    assert send.call_count == 1
    recovery.report_changes([], state, send)
    assert send.call_count == 2
    assert send.call_args.args[0] == "Resolved: gap-fill: last run failed"
    recovery.report_changes([], state, send)
    assert send.call_count == 2


def test_failed_alert_is_retried_and_incomplete_check_does_not_claim_recovery():
    state, send = {}, Mock(return_value=False)
    recovery.report_changes(["BlueBubbles server is not responding to ping"], state, send)
    assert not state
    send.return_value = True
    recovery.report_changes(["BlueBubbles server is not responding to ping"], state, send)
    assert send.call_count == 2
    recovery.report_changes(
        ["Health check could not start: OperationalError"], state, send, incomplete=True
    )
    assert "Resolved" not in send.call_args.args[0]
    assert len(state["reported_issues"]) == 2


def test_increasing_job_age_does_not_repeat_alert():
    state, send = {}, Mock(return_value=True)
    for age in [20, 25, 30]:
        recovery.report_changes(
            [f"Expected job scores last ran {age} minutes ago (limit 15)"], state, send
        )
    assert send.call_count == 1


def test_state_is_saved_even_if_check_raises(tmp_path):
    with pytest.raises(RuntimeError), recovery.health_state(tmp_path) as (state, save):
        state["bluebubbles"] = {"attempts": 1}
        save()
        raise RuntimeError("check interrupted")
    with recovery.health_state(tmp_path) as (state, _save):
        assert state["bluebubbles"]["attempts"] == 1
