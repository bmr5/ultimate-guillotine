import subprocess
import sys


def test_trades_help_lists_commands() -> None:
    result = subprocess.run([sys.executable, "-m", "ultimate_guillotine.cli.main", "trades", "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    for name in ("extract", "list", "retry", "replay"):
        assert name in result.stdout
