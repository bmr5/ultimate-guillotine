import json
import subprocess
from pathlib import Path

import pytest

from ultimate_guillotine.video import higgsfield as hf


def test_a_reference_makes_it_an_omni_reference_job() -> None:
    req = hf.GenerateRequest(prompt="anchor", reference_video=Path("ref.mp4"), duration=8)
    cmd = hf.create_command(req, binary="/opt/homebrew/bin/higgsfield")
    assert cmd[:4] == ["/opt/homebrew/bin/higgsfield", "generate", "create", "seedance_2_5"]
    assert cmd[cmd.index("--mode") + 1] == "omni_reference"
    assert cmd[cmd.index("--video-references") + 1] == "ref.mp4"
    assert cmd[cmd.index("--generate_audio") + 1] == "false"
    assert cmd[-1] == "--json" and "--wait" not in cmd


def test_no_reference_is_text_to_video() -> None:
    cmd = hf.cost_command(hf.GenerateRequest(prompt="anchor"))
    assert cmd[:4] == ["higgsfield", "generate", "cost", "seedance_2_5"]
    assert cmd[cmd.index("--mode") + 1] == "t2v" and "--video-references" not in cmd
    assert cmd[-1] == "--json"


def test_get_command_asks_for_one_job() -> None:
    assert hf.get_command("j1") == ["higgsfield", "generate", "get", "j1", "--json"]


def test_parse_credits() -> None:
    assert hf.parse_credits('{"credits": 52}\n') == 52


def test_parse_job_reads_the_document_or_the_first_of_a_list() -> None:
    doc = {"id": "j1", "status": "completed", "result_url": "https://cdn/x.mp4", "params": {}}
    assert hf.parse_job(json.dumps(doc)) == hf.Job("j1", "completed", "https://cdn/x.mp4")
    assert hf.parse_job(json.dumps([{"id": "j2", "status": "queued", "result_url": None}])) == (
        hf.Job("j2", "queued", None)
    )


def test_parse_job_falls_back_to_an_mp4_url_and_rejects_junk() -> None:
    assert hf.parse_job('{"id": "j3", "status": "done", "note": "https://cdn/y.mp4"}') == (
        hf.Job("j3", "done", "https://cdn/y.mp4")
    )
    with pytest.raises(hf.HiggsfieldError):
        hf.parse_job("not json")
    with pytest.raises(hf.HiggsfieldError):
        hf.parse_job('{"status": "queued"}')


def test_run_reports_the_cli_error() -> None:
    def fake_run(cmd, **_k):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Error: Session expired")

    with pytest.raises(hf.HiggsfieldError, match="Session expired"):
        hf.run(["higgsfield"], run=fake_run)


class Polls:
    """A runner that answers `generate get` from a scripted list of outcomes."""

    def __init__(self, outcomes: list) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0
        self.slept: list[float] = []

    def runner(self, cmd):
        assert cmd[1:3] == ["generate", "get"]
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return json.dumps(outcome)

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


def test_wait_polls_until_the_result_appears() -> None:
    polls = Polls(
        [
            {"id": "j1", "status": "queued", "result_url": None},
            {"id": "j1", "status": "in_progress", "result_url": None},
            {"id": "j1", "status": "completed", "result_url": "https://cdn/z.mp4"},
        ]
    )
    url = hf.wait_for("j1", runner=polls.runner, sleep=polls.sleep, clock=lambda: 0.0)
    assert url == "https://cdn/z.mp4" and polls.calls == 3 and polls.slept == [15, 15]


def test_wait_survives_a_transient_poll_error() -> None:
    polls = Polls(
        [
            hf.HiggsfieldError("502 Bad Gateway"),
            {"id": "j1", "status": "completed", "result_url": "https://cdn/z.mp4"},
        ]
    )
    assert hf.wait_for("j1", runner=polls.runner, sleep=polls.sleep, clock=lambda: 0.0)


def test_wait_gives_up_after_repeated_poll_errors() -> None:
    polls = Polls([hf.HiggsfieldError("down")] * hf.POLL_FAILURES)
    with pytest.raises(hf.HiggsfieldError, match="j1: down"):
        hf.wait_for("j1", runner=polls.runner, sleep=polls.sleep, clock=lambda: 0.0)


def test_wait_raises_when_the_job_fails() -> None:
    polls = Polls([{"id": "j1", "status": "failed", "result_url": None}])
    with pytest.raises(hf.HiggsfieldError, match="j1 failed"):
        hf.wait_for("j1", runner=polls.runner, sleep=polls.sleep, clock=lambda: 0.0)


def test_wait_times_out_with_the_last_known_state() -> None:
    ticks = iter([0.0, 0.0, 100.0, 100.0])
    polls = Polls([{"id": "j1", "status": "in_progress", "result_url": None}] * 3)
    with pytest.raises(hf.HiggsfieldError, match="still in_progress after 60 s"):
        hf.wait_for(
            "j1", runner=polls.runner, sleep=polls.sleep, clock=lambda: next(ticks), timeout=60
        )


def test_generate_clip_creates_reports_waits_and_fetches(tmp_path: Path) -> None:
    seen: dict = {"reports": []}
    answers = iter(
        [
            json.dumps([{"id": "j9", "status": "queued", "result_url": None}]),
            json.dumps({"id": "j9", "status": "completed", "result_url": "https://cdn/q.mp4"}),
        ]
    )

    def runner(cmd):
        seen.setdefault("cmds", []).append(cmd)
        return next(answers)

    def fetch(url, dest):
        seen["url"] = url
        dest.write_bytes(b"mp4")
        return dest

    out = hf.generate_clip(
        hf.GenerateRequest(prompt="p"),
        tmp_path / "gen.mp4",
        runner=runner,
        fetch=fetch,
        report=seen["reports"].append,
        sleep=lambda _s: None,
        clock=lambda: 0.0,
    )
    assert out.read_bytes() == b"mp4" and seen["url"] == "https://cdn/q.mp4"
    assert seen["cmds"][0][1:3] == ["generate", "create"]
    assert seen["cmds"][0][seen["cmds"][0].index("--prompt") + 1] == "p"
    assert seen["cmds"][1] == ["higgsfield", "generate", "get", "j9", "--json"]
    assert seen["reports"] == ["higgsfield job j9 queued"]
