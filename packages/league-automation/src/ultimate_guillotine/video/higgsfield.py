"""Footage from Seedance 2.5 on Higgsfield, through the ``higgsfield`` CLI.

The CLI is already installed and logged in (the ugc-studio account). A job is
one ``generate create`` call with ``--wait --json``; the finished job document
carries ``result_url``, which is fetched into the media folder. Every call is
injectable so the tests never spend credits.
"""

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx

MODEL = "seedance_2_5"
WAIT_TIMEOUT = "20m"
_MP4_URL = re.compile(r"https://[^\s\"']+\.mp4")


class HiggsfieldError(RuntimeError):
    """The CLI failed or its output carried no result."""


@dataclass(frozen=True)
class GenerateRequest:
    prompt: str
    reference_video: Path | None = None
    duration: int = 8
    resolution: str = "720p"
    aspect_ratio: str = "9:16"
    generate_audio: bool = False

    @property
    def mode(self) -> str:
        return "omni_reference" if self.reference_video else "t2v"


def _params(req: GenerateRequest) -> list[str]:
    params = [
        *("--prompt", req.prompt),
        *("--mode", req.mode),
        *("--duration", str(req.duration)),
        *("--resolution", req.resolution),
        *("--aspect_ratio", req.aspect_ratio),
        *("--generate_audio", "true" if req.generate_audio else "false"),
    ]
    if req.reference_video is not None:
        params += ["--video-references", str(req.reference_video)]
    return params


def create_command(req: GenerateRequest, binary: str = "higgsfield") -> list[str]:
    return [
        binary,
        *("generate", "create", MODEL),
        *_params(req),
        *("--wait", "--wait-timeout", WAIT_TIMEOUT, "--json"),
    ]


def cost_command(req: GenerateRequest, binary: str = "higgsfield") -> list[str]:
    return [binary, "generate", "cost", MODEL, *_params(req), "--json"]


def parse_credits(stdout: str) -> int:
    return int(json.loads(stdout)["credits"])


def _find(obj, key: str):
    if isinstance(obj, dict):
        if obj.get(key):
            return obj[key]
        for value in obj.values():
            found = _find(value, key)
            if found:
                return found
    if isinstance(obj, list):
        for value in obj:
            found = _find(value, key)
            if found:
                return found
    return None


def parse_result_url(stdout: str) -> str:
    """The finished job's video: ``result_url`` in the job document (the shape
    ``higgsfield generate list --json`` shows), else any .mp4 URL in the output."""
    try:
        doc = json.loads(stdout)
    except json.JSONDecodeError:
        doc = None
    url = _find(doc, "result_url") if doc is not None else None
    if not url:
        match = _MP4_URL.search(stdout)
        if match is None:
            raise HiggsfieldError("higgsfield finished without a result url")
        url = match.group(0)
    return url


def run(cmd: list[str], run=subprocess.run) -> str:
    result = run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()[-500:]
        raise HiggsfieldError(message or "higgsfield failed")
    return result.stdout


def download(url: str, dest: Path, client: httpx.Client | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    client = client or httpx.Client(follow_redirects=True, timeout=120)
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in response.iter_bytes():
                fh.write(chunk)
    return dest


def generate_clip(
    req: GenerateRequest, dest: Path, binary: str = "higgsfield", runner=run, fetch=download
) -> Path:
    return fetch(parse_result_url(runner(create_command(req, binary))), dest)
