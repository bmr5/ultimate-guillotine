"""The Hermes-CLI structured-output client, driven through a fake runner."""

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import BaseModel

from ultimate_guillotine.ai import hermes as hermes_module
from ultimate_guillotine.ai.hermes import HermesStructuredClient
from ultimate_guillotine.ai.structured import AIInvalidOutput, AIUnavailable

SESSION = "\nsession_id: 20260909_090556_b1ab3b"


class Shape(BaseModel):
    name: str
    sides: int


class FakeRunner:
    """Answers each call from `outputs`, recording the query file's contents."""

    def __init__(self, *outputs, returncode: int = 0, raises: Exception | None = None) -> None:
        self.outputs = list(outputs)
        self.returncode = returncode
        self.raises = raises
        self.calls: list[tuple[list[str], dict]] = []
        self.queries: list[str] = []
        self.query_paths: list[Path] = []
        self.modes: list[int] = []

    def __call__(self, args, **kwargs):
        path = Path(args[args.index("--query-file") + 1])
        self.queries.append(path.read_text(encoding="utf-8"))
        self.query_paths.append(path)
        self.modes.append(path.stat().st_mode & 0o777)
        self.calls.append((args, kwargs))
        if self.raises is not None:
            raise self.raises
        stdout = self.outputs.pop(0) if self.outputs else ""
        return subprocess.CompletedProcess(args, self.returncode, stdout, SESSION)


def client(runner, **kwargs) -> HermesStructuredClient:
    return HermesStructuredClient(
        "/tmp/profile", runner=runner, binary="/bin/hermes-stub", **kwargs
    )


def test_parse_returns_the_model_and_the_session_id() -> None:
    runner = FakeRunner(json.dumps({"name": "square", "sides": 4}))
    shape, usage = client(runner, model="gpt-5.6-sol").parse("sys", "user text", Shape, "shape")
    assert shape == Shape(name="square", sides=4)
    assert usage.response_id == "20260909_090556_b1ab3b"
    assert usage.model == "gpt-5.6-sol"
    assert usage.prompt_tokens == 0 and usage.completion_tokens == 0


def test_parse_passes_the_profile_home_the_flags_and_the_model() -> None:
    runner = FakeRunner(json.dumps({"name": "square", "sides": 4}))
    client(runner, model="gpt-5.6-sol").parse("sys", "user text", Shape, "shape")
    args, kwargs = runner.calls[0]
    assert args[0] == "/bin/hermes-stub" and args[1] == "chat"
    for flag in ("-Q", "--oneshot", "--reasoning", "none", "--ignore-rules", "--source", "tool"):
        assert flag in args
    assert args[args.index("-t") + 1] == ""
    assert args[args.index("-m") + 1] == "gpt-5.6-sol"
    assert kwargs["env"]["HERMES_HOME"] == "/tmp/profile"
    assert kwargs["capture_output"] is True and kwargs["text"] is True
    assert kwargs["timeout"] == 60.0


def test_the_binary_is_located_through_the_shared_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no explicit `binary` the client asks `hermes_cli`, which is the only
    thing that finds the CLI under launchd's PATH."""
    monkeypatch.setattr(hermes_module, "hermes_binary", lambda: "/opt/found/hermes")
    runner = FakeRunner(json.dumps({"name": "square", "sides": 4}))
    subject = HermesStructuredClient("/tmp/profile", runner=runner, binary=None)
    subject.parse("sys", "user text", Shape, "shape")
    assert runner.calls[0][0][0] == "/opt/found/hermes"


def test_parse_omits_the_model_flag_when_no_override_is_configured() -> None:
    runner = FakeRunner(json.dumps({"name": "square", "sides": 4}))
    client(runner).parse("sys", "user text", Shape, "shape")
    assert "-m" not in runner.calls[0][0]


def test_the_query_file_carries_the_prompt_the_schema_and_the_user_text() -> None:
    runner = FakeRunner(json.dumps({"name": "square", "sides": 4}))
    client(runner).parse("system prompt", "user text", Shape, "shape")
    query = runner.queries[0]
    assert query.startswith("system prompt\n\n")
    assert "one JSON object that matches this JSON schema named shape" in query
    assert "No prose, no code fences." in query
    assert '"additionalProperties": false' in query
    assert query.endswith("user text")


def test_parse_reads_json_wrapped_in_code_fences() -> None:
    runner = FakeRunner('```json\n{"name": "square", "sides": 4}\n```')
    shape, _usage = client(runner).parse("sys", "user text", Shape, "shape")
    assert shape == Shape(name="square", sides=4)


def test_an_invalid_answer_is_retried_once_with_a_rejection_note() -> None:
    runner = FakeRunner(
        json.dumps({"name": "circle"}), json.dumps({"name": "circle", "sides": 0})
    )
    shape, _usage = client(runner).parse("sys", "secret user text", Shape, "shape")
    assert shape == Shape(name="circle", sides=0)
    assert len(runner.calls) == 2
    retry = runner.queries[1]
    assert retry.startswith(runner.queries[0])
    assert "Your previous answer was rejected:" in retry
    assert "Reply again with only the corrected JSON." in retry
    assert retry.count("secret user text") == 1


def test_the_retry_gets_only_what_is_left_of_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One budget covers the call and its retry: the listener waits for `parse`, not
    for a subprocess, so two full-length calls would double the timeout it asked for."""
    clock = iter([0.0, 10.0])
    monkeypatch.setattr(hermes_module, "monotonic", lambda: next(clock))
    runner = FakeRunner(
        json.dumps({"name": "circle"}), json.dumps({"name": "circle", "sides": 0})
    )
    client(runner, timeout=60.0).parse("sys", "user text", Shape, "shape")
    assert runner.calls[0][1]["timeout"] == 60.0
    assert runner.calls[1][1]["timeout"] == 50.0


def test_the_retry_is_skipped_when_almost_none_of_the_budget_is_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry with seconds left would time out and raise the same rejection anyway,
    having kept the caller waiting for the rest of the budget first."""
    clock = iter([0.0, 57.0])
    monkeypatch.setattr(hermes_module, "monotonic", lambda: next(clock))
    runner = FakeRunner(json.dumps({"name": "circle"}))
    with pytest.raises(AIInvalidOutput):
        client(runner, timeout=60.0).parse("sys", "user text", Shape, "shape")
    assert len(runner.calls) == 1


def test_two_invalid_answers_raise_invalid_output() -> None:
    runner = FakeRunner(json.dumps({"name": "circle"}), "still not right")
    with pytest.raises(AIInvalidOutput):
        client(runner).parse("sys", "user text", Shape, "shape")
    assert len(runner.calls) == 2


def test_empty_output_raises_invalid_output_without_a_retry() -> None:
    runner = FakeRunner("   ")
    with pytest.raises(AIInvalidOutput):
        client(runner).parse("sys", "user text", Shape, "shape")
    assert len(runner.calls) == 1


def test_a_non_zero_exit_raises_unavailable_and_never_echoes_the_output() -> None:
    runner = FakeRunner("Member01 trades Player Alpha", returncode=2)
    with pytest.raises(AIUnavailable) as info:
        client(runner).parse("sys", "user text", Shape, "shape")
    assert "2" in str(info.value)
    assert "Member01" not in str(info.value)
    assert "user text" not in str(info.value)


def test_a_timeout_raises_unavailable_by_class_name() -> None:
    runner = FakeRunner(raises=subprocess.TimeoutExpired("hermes", 60.0))
    with pytest.raises(AIUnavailable) as info:
        client(runner).parse("sys", "user text", Shape, "shape")
    assert "TimeoutExpired" in str(info.value)


def test_a_missing_binary_raises_unavailable() -> None:
    runner = FakeRunner(raises=FileNotFoundError("hermes"))
    with pytest.raises(AIUnavailable) as info:
        client(runner).parse("sys", "user text", Shape, "shape")
    assert "FileNotFoundError" in str(info.value)


def test_the_query_file_is_owner_only_and_removed_afterwards() -> None:
    runner = FakeRunner(json.dumps({"name": "square", "sides": 4}))
    client(runner).parse("sys", "user text", Shape, "shape")
    assert runner.modes == [0o600]
    assert not runner.query_paths[0].exists()


def test_the_query_file_is_removed_when_the_call_fails() -> None:
    runner = FakeRunner(raises=subprocess.TimeoutExpired("hermes", 1.0))
    with pytest.raises(AIUnavailable):
        client(runner).parse("sys", "user text", Shape, "shape")
    assert not runner.query_paths[0].exists()


def test_the_model_name_falls_back_when_the_profile_cannot_be_read(tmp_path: Path) -> None:
    """`tmp_path` has no `config.yaml`, so this asserts the fallback and not the
    contents of whatever a shared `/tmp` path happens to hold."""
    runner = FakeRunner(json.dumps({"name": "square", "sides": 4}))
    subject = HermesStructuredClient(str(tmp_path), runner=runner, binary="/bin/hermes-stub")
    _shape, usage = subject.parse("sys", "user text", Shape, "shape")
    assert usage.model == "hermes"


def test_the_model_name_is_read_from_the_profile_config_once(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text("model:\n  default: gpt-5.6-sol\n", encoding="utf-8")
    runner = FakeRunner(json.dumps({"name": "square", "sides": 4}))
    subject = HermesStructuredClient(str(tmp_path), runner=runner, binary="/bin/hermes-stub")
    _shape, usage = subject.parse("sys", "user text", Shape, "shape")
    assert usage.model == "gpt-5.6-sol"
    assert "-m" not in runner.calls[0][0]
