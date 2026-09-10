from datetime import UTC, datetime, timedelta
from pathlib import Path

from ultimate_guillotine.trades.models import TradeAsset, TradeParty
from ultimate_guillotine.video import ffmpeg as ff
from ultimate_guillotine.video import pipeline
from ultimate_guillotine.video.assets import Assets
from ultimate_guillotine.video.higgsfield import HiggsfieldError
from ultimate_guillotine.video.jobs import VideoJob
from ultimate_guillotine.video.script import Beat, Script
from ultimate_guillotine.video.worker import AGENT, STALE_AFTER, Worker

NOW = datetime(2026, 9, 10, 15, 0, tzinfo=UTC)
TERMS = {
    "season": 2026,
    "effective_week": 1,
    "kind": "permanent",
    "parties": [TradeParty(1, "Member01"), TradeParty(2, "Member02")],
    "assets": [TradeAsset("player", 1, 2, "p1", "Rhamondre", None, None, None)],
    "source_message_guid": "alert-1",
    "evidence_excerpt": "trade",
    "prompt_version": "t",
    "model": "t",
}


def job(job_id: int = 1, attempts: int = 1) -> VideoJob:
    return VideoJob(
        job_id,
        5,
        "TEST-2026-002",
        "running",
        "reply-1",
        NOW,
        NOW,
        None,
        attempts,
        None,
        None,
        "iMessage;+;chat-test",
    )


class FakeJobs:
    def __init__(self, queued: VideoJob | None) -> None:
        self.queued = queued
        self.finished: list[tuple[int, str]] = []
        self.failed: list[tuple[int, str]] = []
        self.stale_calls: list[tuple[timedelta, datetime]] = []

    def fail_stale(self, older_than, now):
        self.stale_calls.append((older_than, now))
        return []

    def claim(self):
        queued, self.queued = self.queued, None
        return queued

    def finish(self, job_id, output_path):
        self.finished.append((job_id, output_path))

    def fail(self, job_id, error):
        self.failed.append((job_id, error))


class FakeTrades:
    def find_by_id(self, trade_id):
        return {
            "trade_id": trade_id,
            "trade_code": "TEST-2026-002",
            "status": "accepted",
            "terms": TERMS,
        }


class FakeMembers:
    def all_members(self):
        return []


class FakeRuns:
    def __init__(self) -> None:
        self.reserved: list[tuple] = []
        self.finished: list[tuple] = []

    def reserve(self, agent, trigger, key, invoked_by=None):
        self.reserved.append((agent, trigger, key))
        return 11

    def finish(self, run_id, status, output_hash=None, error=None, input_version=None):
        self.finished.append((run_id, status, error))


class FakeDelivery:
    def __init__(self) -> None:
        self.attachments: list[tuple] = []

    def deliver_attachment(self, run_id, agent, filename, data, reply_to=None):
        self.attachments.append((run_id, agent, filename, data, reply_to))


class FakeConn:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def fake_script(_client, copy, seconds):
    return Script(
        beats=[Beat(start=0, end=seconds or 4, direction="urgent", text="Breaking news.")]
    )


def worker(tmp_path: Path, queued: VideoJob | None, render) -> tuple[Worker, dict]:
    parts = {
        "jobs": FakeJobs(queued),
        "runs": FakeRuns(),
        "delivery": FakeDelivery(),
        "conn": FakeConn(),
        "notes": [],
    }
    w = Worker(
        conn=parts["conn"],
        jobs=parts["jobs"],
        trades=FakeTrades(),
        members=FakeMembers(),
        runs=parts["runs"],
        delivery=parts["delivery"],
        notify=parts["notes"].append,
        assets=Assets(tmp_path),
        script_ai=lambda: object(),
        ffmpeg="ffmpeg",
        ffprobe="ffprobe",
        render=render,
        write_script=fake_script,
        now=lambda: NOW,
    )
    return w, parts


def rendered(tmp_path: Path):
    def render(request, assets, *, ffmpeg, ffprobe, report):
        assert request.voiced and request.base == "generated" and request.name == "TEST-2026-002"
        assert request.script.read == "Breaking news." and request.music_gain_db == -12.0
        assert request.generate_seconds is None
        assert request.copy.headline == "SOURCES: RHAMONDRE TRADED TO MEMBER02"
        report("higgsfield job j1 queued")
        out = tmp_path / "TEST-2026-002-x.mp4"
        out.write_bytes(b"mp4")
        composite = ff.Composite(footage=out, card=out, music=out, output=out)
        return pipeline.Job(out, out, 0.0, 12.0, composite, ["ffmpeg"])

    return render


def test_idle_when_nothing_is_queued(tmp_path: Path) -> None:
    w, parts = worker(tmp_path, None, rendered(tmp_path))
    outcome = w.run_once()
    assert outcome.status == "idle" and outcome.job_id is None
    assert parts["jobs"].stale_calls == [(STALE_AFTER, NOW)]
    assert parts["delivery"].attachments == []


def test_a_queued_job_is_rendered_delivered_and_finished(tmp_path: Path) -> None:
    w, parts = worker(tmp_path, job(), rendered(tmp_path))
    outcome = w.run_once()
    assert outcome.status == "done" and outcome.job_id == 1
    assert parts["runs"].reserved == [(AGENT, "video-job", "video:1:1")]
    assert parts["delivery"].attachments == [
        (11, AGENT, "TEST-2026-002-x.mp4", b"mp4", "iMessage;+;chat-test")
    ]
    assert parts["jobs"].finished == [(1, str(tmp_path / "TEST-2026-002-x.mp4"))]
    assert parts["runs"].finished == [(11, "succeeded", None)]
    assert parts["notes"] == ["TEST-2026-002: higgsfield job j1 queued"]
    assert parts["conn"].commits >= 3
    assert str(outcome).startswith("job 1 done: ")


def test_a_failed_render_is_recorded_reported_and_not_delivered(tmp_path: Path) -> None:
    def broken(request, assets, *, ffmpeg, ffprobe, report):
        raise HiggsfieldError("job j2 failed")

    w, parts = worker(tmp_path, job(attempts=2), broken)
    outcome = w.run_once()
    assert outcome.status == "failed"
    assert parts["jobs"].failed == [(1, "HiggsfieldError: job j2 failed")]
    assert parts["runs"].reserved == [(AGENT, "video-job", "video:1:2")]
    assert parts["runs"].finished == [(11, "failed", "HiggsfieldError")]
    assert parts["delivery"].attachments == []
    assert parts["notes"] == ["trade video TEST-2026-002 failed — HiggsfieldError: job j2 failed"]
    assert parts["conn"].rollbacks == 1
