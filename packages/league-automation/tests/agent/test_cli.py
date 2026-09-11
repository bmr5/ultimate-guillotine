"""Exercise the whole dry-run worker without a model, writes, or messages."""

import argparse
import copy
import json
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import Mock

import pytest

from ultimate_guillotine.agent.session import AgentReply
from ultimate_guillotine.agent.tools.source import FixtureSource
from ultimate_guillotine.cli import agent as cli
from ultimate_guillotine.cli.main import build_parser
from ultimate_guillotine.trades.models import MemberRef

RESEARCH = {
    "kind": "answer",
    "chat_text": "Bench 05-0 is on Member05's roster.",
    "report": {"title": "Holding Bowers", "question": "Who holds Bench 05-0?",
               "html_body": "<p class='card'>Member05 holds Bench 05-0.</p>", "sources": []},
    "facts": {"players": [{"player_id": "p05b0", "name": "Bench 05-0",
                           "holder": "Member05"}], "faab": [], "proposals": []},
    "source_line": "Source: rosters",
}


class FakeClient:
    instances: ClassVar[list] = []

    def __init__(self, home, **kwargs):
        self.home, self.kwargs, self.calls = home, kwargs, []
        self.instances.append(self)

    def run(self, query, *, resume=None):
        self.calls.append((query, resume))
        return AgentReply("```json\n" + json.dumps(RESEARCH) + "\n```", "sess-9", "fake-model")


def ask_args(tmp_path, **kwargs):
    return argparse.Namespace(**{
        "text": "Who holds Bench 05-0?", "member": "Member05", "resume": None,
        "fixture": True, "out": str(tmp_path), **kwargs,
    })


def test_matching_members():
    members = [MemberRef(1, "Member01", ("max",)),
               MemberRef(2, "Member02", ("max", "mp"), "Public Nick", "Sleeper Label")]
    for wanted in ("member 02", "public nick", "SLEEPER LABEL", "mp"):
        assert [m.member_id for m in cli.matching_members(members, wanted)] == [2]
    assert [m.member_id for m in cli.matching_members(members, "MAX")] == [1, 2]


def test_parser():
    args = build_parser().parse_args([
        "agent", "ask", "--text", "hi", "--as", "Member05", "--fixture", "--out", "/tmp/x",
        "--resume", "old-session",
    ])
    assert args.command == "ask" and args.member == "Member05" and args.fixture
    assert args.resume == "old-session" and args.handler == cli.cmd_ask
    assert build_parser().parse_args(["agent", "answers", "--last", "3"]).last == 3


@pytest.mark.parametrize("resume", [None, "old-session"])
def test_fixture_whole_worker(monkeypatch, tmp_path, capsys, resume):
    monkeypatch.setattr(cli, "HermesAgentClient", FakeClient)
    monkeypatch.setattr(cli, "connect", Mock(side_effect=AssertionError("no database")))
    monkeypatch.setenv("HERMES_LEAGUE_PROFILE_HOME", str(tmp_path / "profile"))
    monkeypatch.setenv("HERMES_MODEL", "fixture-model")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert cli.cmd_ask(ask_args(tmp_path, resume=resume)) == 0
    output = capsys.readouterr()
    assert RESEARCH["chat_text"] in output.out
    assert "session: sess-9" in output.out and "outcome: answer" in output.out
    assert "run: succeeded" in output.out and not output.err
    assert "Member05 holds Bench 05-0." in (
        tmp_path / "holding-bowers-week-6.html"
    ).read_text()
    client = FakeClient.instances[-1]
    assert client.home == str(tmp_path / "profile")
    assert client.kwargs == {"model": "fixture-model", "extra_env": {"UG_AGENT_FIXTURE": "1"}}
    assert len(client.calls) == 1 and client.calls[0][1] == resume


@pytest.mark.parametrize("member,error", [("Nobody", "unknown"), ("shared", "ambiguous")])
def test_invalid_asker_before_model(monkeypatch, tmp_path, capsys, member, error):
    client = Mock(side_effect=AssertionError("model constructed"))
    monkeypatch.setattr(cli, "HermesAgentClient", client)
    monkeypatch.setattr(FixtureSource, "members", lambda self: [
        MemberRef(1, "One", ("shared",)), MemberRef(2, "Two", ("shared",)),
    ])
    assert cli.cmd_ask(ask_args(tmp_path, member=member)) == 2
    assert f"{error} member" in capsys.readouterr().err
    client.assert_not_called()


@pytest.mark.parametrize("failure", ["exception", "verification"])
def test_failure_exit_status(monkeypatch, tmp_path, capsys, failure):
    client = Mock()
    if failure == "exception":
        client.run.side_effect = RuntimeError("private detail")
    else:
        invalid = copy.deepcopy(RESEARCH)
        invalid["facts"]["players"][0]["holder"] = "Member02"
        client.run.return_value = AgentReply(json.dumps(invalid), "sess-9", "fake")
    monkeypatch.setattr(cli, "HermesAgentClient", lambda *a, **kw: client)
    assert cli.cmd_ask(ask_args(tmp_path)) == 1
    output = capsys.readouterr()
    assert "outcome: " + ("failed" if failure == "exception" else "rejected") in output.out
    assert "private detail" not in output.err
    assert not list(tmp_path.glob("*.html"))


def live_deps(monkeypatch):
    conn, http = Mock(), Mock()
    monkeypatch.setattr(cli, "load_settings", lambda: SimpleNamespace(
        hermes_league_profile_home="profile", hermes_model=None, sleeper_league_id="league",
    ))
    monkeypatch.setattr(cli, "connect", lambda settings: conn)
    monkeypatch.setattr(cli.httpx, "Client", lambda: http)
    return conn, http


@pytest.mark.parametrize("mode", ["success", "unknown", "source-error", "client-error"])
def test_live_resources_close(monkeypatch, tmp_path, mode):
    conn, http = live_deps(monkeypatch)
    source = FixtureSource()
    if mode == "source-error":
        source.members = Mock(side_effect=RuntimeError("source failed"))
    monkeypatch.setattr(cli, "DatabaseSource", lambda *args: source)
    monkeypatch.setattr(cli, "HermesAgentClient", FakeClient if mode != "client-error" else
                        Mock(side_effect=RuntimeError("client failed")))
    args = ask_args(tmp_path, fixture=False, member="Nobody" if mode == "unknown" else "Member05")
    if mode.endswith("error"):
        with pytest.raises(RuntimeError):
            cli.cmd_ask(args)
    else:
        assert cli.cmd_ask(args) == (2 if mode == "unknown" else 0)
    assert conn.read_only is True
    conn.close.assert_called_once()
    http.close.assert_called_once()
    conn.commit.assert_not_called()


@pytest.mark.parametrize("fail", [False, True])
def test_answers_history_closes_connection(monkeypatch, capsys, fail):
    conn, http = live_deps(monkeypatch)
    repo = Mock()
    repo.recent.return_value = [SimpleNamespace(
        kind="answer", model="fake", run_id=9, is_follow_up=True,
        question="question", chat_text="reply", report_title="Report",
    )]
    if fail:
        repo.recent.side_effect = RuntimeError("query failed")
    monkeypatch.setattr(cli, "AgentAnswerRepository", lambda connection: repo)
    if fail:
        with pytest.raises(RuntimeError):
            cli.cmd_answers(argparse.Namespace(last=3))
    else:
        assert cli.cmd_answers(argparse.Namespace(last=3)) == 0
        output = capsys.readouterr().out
        for text in ("[answer] fake · run 9 · follow-up", "Q: question", "A: reply",
                     "write-up: Report"):
            assert text in output
    repo.recent.assert_called_once_with(3)
    conn.close.assert_called_once()
    assert conn.read_only is True
    conn.commit.assert_not_called()
    http.close.assert_not_called()


def test_artifact_write_failure_is_nonzero(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "HermesAgentClient", FakeClient)
    target = tmp_path / "not-a-directory"
    target.write_text("existing file")
    assert cli.cmd_ask(ask_args(target)) == 1
    assert "artifact:" not in capsys.readouterr().out
    assert target.read_text() == "existing file"


def test_answers_invalid_limit_never_connects(monkeypatch, capsys):
    connect = Mock(side_effect=AssertionError("no database"))
    monkeypatch.setattr(cli, "connect", connect)
    assert cli.cmd_answers(argparse.Namespace(last=0)) == 2
    assert "--last must be positive" in capsys.readouterr().err
    connect.assert_not_called()


def test_http_construction_failure_closes_database(monkeypatch, tmp_path):
    conn, _ = live_deps(monkeypatch)
    monkeypatch.setattr(cli.httpx, "Client", Mock(side_effect=RuntimeError("HTTP setup")))
    with pytest.raises(RuntimeError):
        cli.cmd_ask(ask_args(tmp_path, fixture=False))
    conn.close.assert_called_once()
    conn.commit.assert_not_called()
