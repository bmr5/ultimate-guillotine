"""One `hermes chat` per turn, with exactly the flags the spec names."""

import subprocess
from pathlib import Path

import pytest

from ultimate_guillotine.agent.session import (
    FLAGS,
    HANG_GUARD_SECONDS,
    HermesAgentClient,
    SessionNotFound,
)
from ultimate_guillotine.ai.structured import AIInvalidOutput, AIUnavailable


class Runner:
    def __init__(self, stdout="ok", stderr="session_id: sess-1\n", returncode=0, error=None):
        self.stdout, self.stderr, self.returncode, self.error = stdout, stderr, returncode, error
        self.calls: list[dict] = []

    def __call__(self, command, **kwargs):
        query_file = command[command.index("--query-file") + 1]
        self.calls.append({
            "command": command, "kwargs": kwargs, "query": Path(query_file).read_text(),
            "query_file": query_file,
        })
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(command, self.returncode, self.stdout, self.stderr)


def _client(runner, **kw) -> HermesAgentClient:
    return HermesAgentClient("~/.hermes/profiles/guillotine-league", runner=runner,
                             binary="/bin/hermes", **kw)


def test_the_command_is_the_spec_line_and_nothing_more() -> None:
    runner = Runner()
    reply = _client(runner).run("hello")
    call = runner.calls[0]
    assert call["command"][:1] == ["/bin/hermes"]
    assert tuple(call["command"][1:1 + len(FLAGS)]) == FLAGS
    assert FLAGS == ("chat", "-Q", "--oneshot", "--reasoning", "high", "--source", "tool")
    for absent in ("-t", "--max-turns", "--run-budget", "--ignore-rules", "--resume"):
        assert absent not in call["command"]
    assert call["query"] == "hello"
    assert not Path(call["query_file"]).exists()
    assert call["kwargs"]["timeout"] == HANG_GUARD_SECONDS == 3600.0
    assert call["kwargs"]["env"]["HERMES_HOME"].endswith("/.hermes/profiles/guillotine-league")
    assert reply.text == "ok" and reply.session_id == "sess-1"


def test_a_follow_up_resumes_and_a_model_override_is_passed() -> None:
    runner = Runner()
    _client(runner, model="gpt-x").run("again", resume="sess-1")
    command = runner.calls[0]["command"]
    assert command[command.index("--resume") + 1] == "sess-1"
    assert command[command.index("-m") + 1] == "gpt-x"


def test_extra_env_reaches_the_subprocess() -> None:
    runner = Runner()
    _client(runner, extra_env={"UG_AGENT_FIXTURE": "1"}).run("x")
    assert runner.calls[0]["kwargs"]["env"]["UG_AGENT_FIXTURE"] == "1"


def test_failures_are_named_by_class_only() -> None:
    with pytest.raises(AIUnavailable, match="code 3"):
        _client(Runner(returncode=3)).run("x")
    with pytest.raises(AIUnavailable, match="TimeoutExpired"):
        _client(Runner(error=subprocess.TimeoutExpired("hermes", 1))).run("x")
    with pytest.raises(AIInvalidOutput):
        _client(Runner(stdout="   ")).run("x")


@pytest.mark.parametrize("code", [0, 1])
def test_only_the_installed_missing_session_diagnostic_is_classified(code):
    runner = Runner(stderr="Session not found: secret-session\n", returncode=code)
    with pytest.raises(SessionNotFound) as caught:
        _client(runner).run("again", resume="secret-session")
    assert str(caught.value) == "hermes session not found"
    assert len(runner.calls) == 1


@pytest.mark.parametrize("stderr,error", [
    ("Authentication failed: private details", None),
    ("Process failed: private details", None),
    ("", subprocess.TimeoutExpired("private command", 3600)),
])
def test_other_failures_remain_unavailable_without_raw_diagnostics(stderr, error):
    with pytest.raises(AIUnavailable) as caught:
        _client(Runner(stderr=stderr, returncode=1, error=error)).run("again", resume="old")
    assert type(caught.value) is AIUnavailable
    assert "private" not in str(caught.value)
