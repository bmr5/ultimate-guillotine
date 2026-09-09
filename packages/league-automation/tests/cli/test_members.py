import subprocess
import sys


def test_members_help_lists_commands() -> None:
    result = subprocess.run([sys.executable, "-m", "ultimate_guillotine.cli.main", "members", "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    for name in ("list", "aliases"):
        assert name in result.stdout
