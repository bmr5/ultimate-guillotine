import subprocess
import sys


def test_ug_help_lists_commands() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ultimate_guillotine.cli.main", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    for name in ("ops", "targets", "sleeper", "ingest", "listener"):
        assert name in result.stdout


def test_ops_health_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ultimate_guillotine.cli.main", "ops", "health", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "--escalate" in result.stdout
