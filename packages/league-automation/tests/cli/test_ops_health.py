from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import Mock

from ultimate_guillotine.cli import ops


def test_scheduled_health_repairs_before_checking_and_alerts_only_on_changes(monkeypatch, tmp_path):
    deps = SimpleNamespace(
        conn=Mock(),
        client=Mock(),
        notifier=Mock(),
        settings=SimpleNamespace(
            hermes_profile_home=str(tmp_path), bluebubbles_server_url="http://localhost:1234"
        ),
    )
    deps.notifier.alerts.return_value = True
    monkeypatch.setattr(ops, "build_deps", lambda: deps)
    monkeypatch.setattr(ops, "run_scheduled", lambda c, a, n, action: action(1))
    events = []
    monkeypatch.setattr(ops, "recover_bluebubbles", lambda *a: events.append("repair"))

    def check(*args):
        events.append("check")
        return ["gap-fill: last run failed at 2026-09-14 13:52 UTC"]

    monkeypatch.setattr(ops, "check_health", check)
    args = Namespace(auto_recover=True, changes_only=True, escalate=True)
    ops.cmd_health(args)
    ops.cmd_health(args)
    assert events == ["repair", "check", "repair", "check"]
    deps.notifier.alerts.assert_called_once()


def test_plain_health_does_not_restart_or_send(monkeypatch, tmp_path):
    deps = SimpleNamespace(
        conn=Mock(),
        client=Mock(),
        notifier=Mock(),
        settings=SimpleNamespace(hermes_profile_home=str(tmp_path)),
    )
    monkeypatch.setattr(ops, "build_deps", lambda: deps)
    monkeypatch.setattr(ops, "run_scheduled", lambda c, a, n, action: action(1))
    recover = Mock()
    monkeypatch.setattr(ops, "recover_bluebubbles", recover)
    monkeypatch.setattr(ops, "check_health", lambda *a: ["BlueBubbles is down"])
    ops.cmd_health(Namespace(auto_recover=False, changes_only=False, escalate=False))
    recover.assert_not_called()
    deps.notifier.alerts.assert_not_called()
