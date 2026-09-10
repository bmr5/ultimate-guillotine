"""`ug targets`, and the one rule it exists to keep: no GUID reaches the terminal.

`set` is the exception and has to be -- the delivery target's identity is checked
against the GUID it is given -- but it answers with a row id. `listen` takes the
league chat from the environment and answers with a count, because the whole
point of shadow mode is that Ben registers the league chat once, at a prompt,
without pasting it anywhere that keeps scrollback.
"""

import argparse
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ultimate_guillotine.cli import targets as targets_cli
from ultimate_guillotine.config import DeliveryMode, Settings

LEAGUE_CHAT = "iMessage;+;chat-league"


class FakeTargets:
    """A target table that records what it was asked to register."""

    def __init__(self, conn) -> None:
        self.registered: list[tuple[str, str]] = []
        self.delivering: dict[DeliveryMode, object] = {}

    def upsert_listen(self, chat_guid: str, label: str) -> int:
        self.registered.append((chat_guid, label))
        return len(self.registered)

    def listen_chat_guids(self) -> list[str]:
        return [guid for guid, _label in self.registered]

    def get(self, mode: DeliveryMode):
        return self.delivering.get(mode)


class FakeConn:
    def commit(self) -> None:
        pass


def _deps(monkeypatch: pytest.MonkeyPatch, repo: FakeTargets, **overrides):
    settings = Settings(
        database_url="postgresql://x:y@example.invalid/db",
        production_chat_guid=overrides.get("production_chat_guid", LEAGUE_CHAT),
        _env_file=None,
    )
    monkeypatch.setattr(
        targets_cli, "build_deps",
        lambda: SimpleNamespace(settings=settings, conn=FakeConn(), client=None, notifier=None),
    )
    monkeypatch.setattr(targets_cli, "TargetRepository", lambda conn: repo)


def test_targets_help_lists_the_listen_command() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ultimate_guillotine.cli.main", "targets", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    for name in ("set", "listen", "counts"):
        assert name in result.stdout


def test_listen_takes_the_league_chat_from_the_environment_and_prints_a_count(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nobody should have to paste a chat GUID at a prompt to turn shadow mode on,
    and nothing that is printed may carry one."""
    repo = FakeTargets(None)
    _deps(monkeypatch, repo)

    code = targets_cli.cmd_listen(argparse.Namespace(chat_guid=None, label="league chat"))

    assert code == 0
    assert repo.registered == [(LEAGUE_CHAT, "league chat")]
    out = capsys.readouterr().out
    assert out == "listen-only chats registered: 1\n"
    assert LEAGUE_CHAT not in out


def test_listen_accepts_an_explicit_chat_and_still_prints_only_a_count(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = FakeTargets(None)
    _deps(monkeypatch, repo, production_chat_guid=None)

    code = targets_cli.cmd_listen(
        argparse.Namespace(chat_guid="iMessage;+;chat-other", label="gulag chat")
    )

    assert code == 0
    assert repo.registered == [("iMessage;+;chat-other", "gulag chat")]
    assert "iMessage" not in capsys.readouterr().out


def test_listen_refuses_when_there_is_no_chat_to_listen_in(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Registering nothing and reporting success would leave shadow mode looking
    switched on and silent, which is the one failure nobody would notice."""
    repo = FakeTargets(None)
    _deps(monkeypatch, repo, production_chat_guid=None)

    code = targets_cli.cmd_listen(argparse.Namespace(chat_guid=None, label="league chat"))

    assert code == 2
    assert repo.registered == []
    assert "PRODUCTION_CHAT_GUID" in capsys.readouterr().out


def test_counts_says_what_is_registered_and_never_which_chats(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = FakeTargets(None)
    repo.delivering[DeliveryMode.TEST] = object()
    _deps(monkeypatch, repo)
    targets_cli.cmd_listen(argparse.Namespace(chat_guid=None, label="league chat"))
    capsys.readouterr()

    code = targets_cli.cmd_counts(argparse.Namespace())

    assert code == 0
    out = capsys.readouterr().out
    assert out.splitlines() == [
        "test delivery target: yes",
        "production delivery target: no",
        "listen-only chats registered: 1",
    ]
    assert "iMessage" not in out
