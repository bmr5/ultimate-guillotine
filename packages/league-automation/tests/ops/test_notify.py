import subprocess

from ultimate_guillotine.ops.notify import HermesNotifier


class FakeRunner:
    def __init__(self, returncode: int = 0) -> None:
        self.calls = []
        self.returncode = returncode

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, self.returncode, "", "")


def test_send_invokes_hermes_send_with_profile_home() -> None:
    runner = FakeRunner()
    notifier = HermesNotifier("/tmp/profile", runner=runner)
    assert notifier.send("#guillotine-ops", "run ok") is True
    args, kwargs = runner.calls[0]
    assert args[0].endswith("hermes")
    assert args[1:4] == ["send", "--to", "discord:#guillotine-ops"]
    assert args[-1] == "run ok"
    assert kwargs["env"]["HERMES_HOME"] == "/tmp/profile"


def test_send_returns_false_on_failure_and_never_raises() -> None:
    notifier = HermesNotifier("/tmp/profile", runner=FakeRunner(returncode=1))
    assert notifier.send("#guillotine-ops", "x") is False
