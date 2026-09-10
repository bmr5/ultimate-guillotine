"""Footage from Seedance 2.5 on Higgsfield, through the ``higgsfield`` CLI.

The CLI is already installed and logged in (the ugc-studio account). A job is
created with ``generate create --json``, which answers with the job document,
and then polled with ``generate get`` until it carries a ``result_url``. The
polling is ours rather than the CLI's ``--wait``: a poll that fails once (a
transient API error while a 12 s clip renders) is retried, and the job id is
reported as soon as it exists, so a clip that cost credits is never lost to a
hiccup in the wait. Every call is injectable so the tests never spend credits.
"""

import json
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

MODEL = "seedance_2_5"
#: A 12 s clip with audio has taken over ten minutes; give a job half an hour.
DEFAULT_TIMEOUT = 30 * 60
POLL_INTERVAL = 15
#: Consecutive failed polls tolerated before the wait gives up.
POLL_FAILURES = 5
FAILED_STATES = frozenset({"failed", "error", "cancelled", "canceled", "rejected"})
_MP4_URL = re.compile(r"https://[^\s\"']+\.mp4")


class HiggsfieldError(RuntimeError):
    """The CLI failed, the job failed, or its output carried no result."""


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


@dataclass(frozen=True)
class Job:
    id: str
    status: str
    result_url: str | None

    @property
    def failed(self) -> bool:
        return self.status.lower() in FAILED_STATES


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
    return [binary, "generate", "create", MODEL, *_params(req), "--json"]


def get_command(job_id: str, binary: str = "higgsfield") -> list[str]:
    return [binary, "generate", "get", job_id, "--json"]


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


def parse_job(stdout: str) -> Job:
    """The job document the CLI prints (``create`` may print a list of them).

    ``result_url`` is read from the document, or as a fallback any .mp4 URL in
    the output, the way an older CLI printed it.
    """
    try:
        doc = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise HiggsfieldError("higgsfield printed no job document") from exc
    if isinstance(doc, list):
        if not doc:
            raise HiggsfieldError("higgsfield printed an empty job list")
        doc = doc[0]
    job_id = _find(doc, "id")
    if not job_id:
        raise HiggsfieldError("higgsfield job document has no id")
    url = _find(doc, "result_url")
    if not url:
        match = _MP4_URL.search(stdout)
        url = match.group(0) if match else None
    return Job(id=str(job_id), status=str(_find(doc, "status") or ""), result_url=url)


def run(cmd: list[str], run=subprocess.run) -> str:
    result = run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()[-500:]
        raise HiggsfieldError(message or "higgsfield failed")
    return result.stdout


def wait_for(
    job_id: str,
    *,
    binary: str = "higgsfield",
    runner: Callable[[list[str]], str] = run,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = POLL_INTERVAL,
) -> str:
    """Poll the job until it has a result; the URL of that result."""
    deadline = clock() + timeout
    failures = 0
    job: Job | None = None
    while True:
        try:
            job = parse_job(runner(get_command(job_id, binary)))
            failures = 0
        except HiggsfieldError as exc:
            failures += 1
            if failures >= POLL_FAILURES:
                raise HiggsfieldError(f"job {job_id}: {exc}") from exc
        if job is not None:
            if job.failed:
                raise HiggsfieldError(f"job {job_id} {job.status}")
            if job.result_url:
                return job.result_url
        if clock() >= deadline:
            state = job.status if job is not None else "unreachable"
            raise HiggsfieldError(f"job {job_id} still {state} after {timeout:.0f} s")
        sleep(interval)


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
    req: GenerateRequest,
    dest: Path,
    binary: str = "higgsfield",
    runner: Callable[[list[str]], str] = run,
    fetch: Callable[[str, Path], Path] = download,
    report: Callable[[str], None] = lambda _line: None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    timeout: float = DEFAULT_TIMEOUT,
) -> Path:
    """Create the job, say which one it is, wait for it, fetch the clip."""
    job = parse_job(runner(create_command(req, binary)))
    report(f"higgsfield job {job.id} {job.status or 'created'}")
    url = job.result_url or wait_for(
        job.id, binary=binary, runner=runner, sleep=sleep, clock=clock, timeout=timeout
    )
    return fetch(url, dest)
