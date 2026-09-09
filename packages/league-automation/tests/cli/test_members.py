import argparse
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ultimate_guillotine.cli import members as members_cli


def test_members_help_lists_commands() -> None:
    result = subprocess.run([sys.executable, "-m", "ultimate_guillotine.cli.main", "members", "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    for name in ("list", "aliases"):
        assert name in result.stdout


class FakeAliasRepo:
    """A repository that knows nobody, the way a fresh members table would."""

    def __init__(self, conn) -> None:
        pass

    def replace_aliases(self, display_name: str, aliases: list[str]) -> int:
        raise ValueError(f"unknown member '{display_name}'")


def test_aliases_load_exits_1_when_every_entry_was_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing was loaded: the file is for another league, or the members table
    has not been synced. Exit 0 would report that as a successful load."""
    path = tmp_path / "aliases.json"
    path.write_text(json.dumps({"members": [{"sleeper_username": "ghost", "aliases": ["g"]}]}))
    conn = SimpleNamespace(commit=lambda: None)
    monkeypatch.setattr(members_cli, "build_deps", lambda: SimpleNamespace(conn=conn))
    monkeypatch.setattr(members_cli, "MemberAliasRepository", FakeAliasRepo)

    exit_code = members_cli.cmd_aliases_load(argparse.Namespace(path=str(path)))

    assert exit_code == 1
    assert "aliases: 0 members, 0 aliases" in capsys.readouterr().out
