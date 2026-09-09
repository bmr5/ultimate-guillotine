import argparse
import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from ultimate_guillotine.cli import members as members_cli
from ultimate_guillotine.data.repositories import MemberContactRepository, handle_hash
from ultimate_guillotine.trades.models import MemberRef


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


class FakeListRepo:
    """One member with a nickname, one without."""

    def __init__(self, conn) -> None:
        pass

    def all_members(self):
        return [
            MemberRef(1, "Member01", ("Benny", "The Hammer"), "Benny"),
            MemberRef(2, "Member02", (), None),
        ]


def test_members_list_prints_the_nickname_and_no_other_alias(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The nickname is the label the board already shows, so printing it here is
    fair game; every other alias stays private, and a member without one gets a
    dash rather than a blank column."""
    monkeypatch.setattr(members_cli, "build_deps", lambda: SimpleNamespace(conn=None))
    monkeypatch.setattr(members_cli, "MemberAliasRepository", FakeListRepo)

    assert members_cli.cmd_list(argparse.Namespace()) == 0

    out = capsys.readouterr().out
    assert "Member01  2  Benny" in out
    assert "Member02  0  -" in out
    assert "Hammer" not in out


def test_members_help_lists_handles() -> None:
    """The handle loader is the only way a sender ever becomes a member, so it
    has to be discoverable from `ug members --help` alongside `aliases`."""
    result = subprocess.run(
        [sys.executable, "-m", "ultimate_guillotine.cli.main", "members", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0 and "handles" in result.stdout


HANDLE = "+15555550100"


@contextmanager
def _noop_transaction():
    yield


class FakeContactRepo:
    """Answers the way the real repository would and records what it was handed."""

    def __init__(self, state: SimpleNamespace) -> None:
        self._state = state

    def replace_handles(self, display_name: str, digests: list[str]) -> int:
        self._state.calls.append((display_name, digests))
        if display_name in self._state.raises:
            raise self._state.raises[display_name]
        if display_name not in self._state.known:
            raise ValueError(f"unknown member: {display_name}")
        return len(digests)


@pytest.fixture
def contact_cli(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """`cmd_handles_load` wired to a `FakeContactRepo` over a do-nothing
    connection, so the loader's own reporting is what is under test.

    The returned state is what the test writes `known`/`raises` into and reads
    `calls` back out of.
    """
    state = SimpleNamespace(known=set(), calls=[], raises={})
    conn = SimpleNamespace(commit=lambda: None, transaction=_noop_transaction)
    monkeypatch.setattr(members_cli, "build_deps", lambda: SimpleNamespace(conn=conn))
    monkeypatch.setattr(
        members_cli, "MemberContactRepository", lambda _conn: FakeContactRepo(state)
    )
    return state


def _handles_file(tmp_path: Path, members: list[dict]) -> str:
    path = tmp_path / "member-handles.json"
    path.write_text(json.dumps({"members": members}), encoding="utf-8")
    return str(path)


def test_handles_load_reports_counts_and_never_prints_a_handle(
    tmp_path: Path, contact_cli, capsys: pytest.CaptureFixture[str]
) -> None:
    """Usernames are league bookkeeping and get printed; a handle is the one
    thing this command exists to keep out of everything a human can read."""
    contact_cli.known = {"Member01", "Member02"}
    path = _handles_file(
        tmp_path,
        [
            {"sleeper_username": "Member01", "handles": [HANDLE, "someone@example.com"]},
            {"sleeper_username": "Member02", "handles": ["+15555550101"]},
        ],
    )

    assert members_cli.cmd_handles_load(argparse.Namespace(path=path)) == 0

    captured = capsys.readouterr()
    assert "handles: 2 members, 3 handles" in captured.out
    assert "skipped" not in captured.out
    for stream in (captured.out, captured.err):
        assert HANDLE not in stream
        assert "5555550100" not in stream
        assert "someone@example.com" not in stream
    # The repo was handed digests, never the handles themselves.
    assert [d for _, digests in contact_cli.calls for d in digests] == [
        handle_hash(HANDLE),
        handle_hash("someone@example.com"),
        handle_hash("+15555550101"),
    ]


def test_handles_load_names_the_unknown_member_on_stderr(
    tmp_path: Path, contact_cli, capsys: pytest.CaptureFixture[str]
) -> None:
    contact_cli.known = {"Member01"}
    path = _handles_file(
        tmp_path,
        [
            {"sleeper_username": "Member01", "handles": [HANDLE]},
            {"sleeper_username": "ghost", "handles": ["+15555550101"]},
        ],
    )

    assert members_cli.cmd_handles_load(argparse.Namespace(path=path)) == 0

    captured = capsys.readouterr()
    assert "handles: 1 members, 1 handles" in captured.out
    assert "skipped: 1" in captured.out
    assert "unknown member: ghost" in captured.err


def test_handles_load_exits_1_when_every_entry_was_skipped(
    tmp_path: Path, contact_cli, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing was loaded, so exit 0 would report a wrong file as a good run."""
    path = _handles_file(tmp_path, [{"sleeper_username": "ghost", "handles": [HANDLE]}])

    assert members_cli.cmd_handles_load(argparse.Namespace(path=path)) == 1

    captured = capsys.readouterr()
    assert "handles: 0 members, 0 handles" in captured.out
    assert "unknown member: ghost" in captured.err


def test_handles_load_skips_an_entry_with_no_handles(
    tmp_path: Path, contact_cli, capsys: pytest.CaptureFixture[str]
) -> None:
    """`replace_handles` is wholesale, so an empty list would unmap the member.
    A half-filled file is not a request to disconnect anybody."""
    contact_cli.known = {"Member01", "Member02", "Member03"}
    path = _handles_file(
        tmp_path,
        [
            {"sleeper_username": "Member01", "handles": [HANDLE]},
            {"sleeper_username": "Member02", "handles": []},
            {"sleeper_username": "Member03"},
        ],
    )

    assert members_cli.cmd_handles_load(argparse.Namespace(path=path)) == 0

    captured = capsys.readouterr()
    assert "handles: 1 members, 1 handles" in captured.out
    assert "skipped: 2" in captured.out
    assert "no handles: Member02" in captured.err
    assert "no handles: Member03" in captured.err
    # Neither empty entry reached the repository at all.
    assert [name for name, _ in contact_cli.calls] == ["Member01"]


def test_handles_load_never_hashes_a_handle_that_is_only_whitespace(
    tmp_path: Path, contact_cli, capsys: pytest.CaptureFixture[str]
) -> None:
    """A blank handle is a hole in the file, not a contact to store.

    `" "` is truthy, so filtering on the raw string kept it: it normalizes to
    nothing and would have been stored as `sha256("")` -- a row no sender can
    ever match and one that every other blank handle in the league would
    collide with, surfacing as a bogus conflict.
    """
    contact_cli.known = {"Member01", "Member02"}
    path = _handles_file(
        tmp_path,
        [
            {"sleeper_username": "Member01", "handles": [" \t ", HANDLE]},
            {"sleeper_username": "Member02", "handles": ["   "]},
        ],
    )

    assert members_cli.cmd_handles_load(argparse.Namespace(path=path)) == 0

    captured = capsys.readouterr()
    assert "handles: 1 members, 1 handles" in captured.out
    assert "no handles: Member02" in captured.err
    assert [(name, digests) for name, digests in contact_cli.calls] == [
        ("Member01", [handle_hash(HANDLE)])
    ]
    assert handle_hash("") not in [d for _, digests in contact_cli.calls for d in digests]


def test_handles_load_propagates_a_conflicting_handle(tmp_path: Path, contact_cli) -> None:
    """An unknown name is a stale row; a handle claimed by two members is a real
    contradiction in the file, and swallowing it would map the wrong person."""
    contact_cli.known = {"Member01", "Member02"}
    contact_cli.raises = {"Member02": ValueError("handle already belongs to another member")}
    path = _handles_file(
        tmp_path,
        [
            {"sleeper_username": "Member01", "handles": [HANDLE]},
            {"sleeper_username": "Member02", "handles": [HANDLE]},
        ],
    )

    with pytest.raises(ValueError, match="another member"):
        members_cli.cmd_handles_load(argparse.Namespace(path=path))


def _seed_member(conn, name: str) -> int:
    with conn.cursor() as cur:
        cur.execute("insert into public.members (display_name) values (%s) returning id", (name,))
        return cur.fetchone()[0]


def test_handles_load_leaves_nothing_behind_when_a_later_entry_conflicts(
    tmp_path: Path, conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file lands whole or not at all. Half a handle file in the database is
    worse than yesterday's: the commissioner cannot tell which half took."""
    _seed_member(conn, "Member01")
    _seed_member(conn, "Member02")
    _seed_member(conn, "Member03")
    repo = MemberContactRepository(conn)
    repo.replace_handles("Member03", [handle_hash("+15555550101")])
    monkeypatch.setattr(members_cli, "build_deps", lambda: SimpleNamespace(conn=conn))
    path = _handles_file(
        tmp_path,
        [
            {"sleeper_username": "Member01", "handles": [HANDLE]},
            {"sleeper_username": "Member02", "handles": ["+1 (555) 555-0101"]},
        ],
    )

    with pytest.raises(ValueError, match="another member"):
        members_cli.cmd_handles_load(argparse.Namespace(path=path))

    # Member01's row went in before the conflict and must not have survived it.
    assert repo.counts() == [("Member03", 1)]
    assert repo.member_for_handle_hash(handle_hash(HANDLE)) is None
