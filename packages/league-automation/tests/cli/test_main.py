import os
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


def test_ops_health_exits_zero_when_database_unreachable() -> None:
    env = {**os.environ, "DATABASE_URL": "postgresql://nobody:nothing@127.0.0.1:1/none"}
    result = subprocess.run(
        [sys.executable, "-m", "ultimate_guillotine.cli.main", "ops", "health"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("Health check could not start:")
