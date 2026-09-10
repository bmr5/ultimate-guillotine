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
    assert cmd[-4:] == ["--wait", "--wait-timeout", "20m", "--json"]


def test_no_reference_is_text_to_video() -> None:
    cmd = hf.cost_command(hf.GenerateRequest(prompt="anchor"))
    assert cmd[:4] == ["higgsfield", "generate", "cost", "seedance_2_5"]
    assert cmd[cmd.index("--mode") + 1] == "t2v" and "--video-references" not in cmd
    assert cmd[-1] == "--json"


def test_parse_credits() -> None:
    assert hf.parse_credits('{"credits": 52}\n') == 52


def test_result_url_comes_from_the_job_document() -> None:
    doc = {"id": "j1", "status": "completed", "result_url": "https://cdn/x.mp4", "params": {}}
    assert hf.parse_result_url(json.dumps(doc)) == "https://cdn/x.mp4"


def test_result_url_falls_back_to_any_mp4_url_in_the_output() -> None:
    assert hf.parse_result_url("done: https://cdn/y.mp4\n") == "https://cdn/y.mp4"
    with pytest.raises(hf.HiggsfieldError):
        hf.parse_result_url('{"status": "failed"}')


def test_run_reports_the_cli_error() -> None:
    def fake_run(cmd, **_k):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Error: Session expired")

    with pytest.raises(hf.HiggsfieldError, match="Session expired"):
        hf.run(["higgsfield"], run=fake_run)


def test_generate_clip_runs_the_job_and_fetches_the_result(tmp_path: Path) -> None:
    seen = {}

    def runner(cmd):
        seen["cmd"] = cmd
        return '{"result_url": "https://cdn/z.mp4"}'

    def fetch(url, dest):
        seen["url"] = url
        dest.write_bytes(b"mp4")
        return dest

    out = hf.generate_clip(
        hf.GenerateRequest(prompt="p"), tmp_path / "gen.mp4", runner=runner, fetch=fetch
    )
    assert out.read_bytes() == b"mp4" and seen["url"] == "https://cdn/z.mp4"
    cmd = seen["cmd"]
    assert cmd[cmd.index("--prompt") + 1] == "p"
