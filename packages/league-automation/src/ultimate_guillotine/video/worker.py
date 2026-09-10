"""Render the next queued trade video and deliver it.

One pass claims one job. The read is written by the model, the footage is
generated with its voice, the composite is encoded, and the file goes to the
chat through ``DeliveryService`` like any other outbound message. A failure is
recorded on the job and on its run and told to ``#guillotine-ops``; nothing is
retried on its own, because every attempt costs credits.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg

from ultimate_guillotine.ai.structured import StructuredOutputClient
from ultimate_guillotine.data.repositories import MemberAliasRepository, RunRepository
from ultimate_guillotine.messages.delivery import DeliveryService
from ultimate_guillotine.trades.format import party_labels
from ultimate_guillotine.trades.models import TradeProposal
from ultimate_guillotine.trades.repository import TradeRepository
from ultimate_guillotine.video import pipeline
from ultimate_guillotine.video.assets import Assets
from ultimate_guillotine.video.copy import trade_copy
from ultimate_guillotine.video.jobs import VideoJobRepository
from ultimate_guillotine.video.script import generate_script

AGENT = "trade-video"
TRIGGER = "video-job"
#: Music under the generated voice.
MUSIC_GAIN_DB = -12.0
#: A render past this is a worker that died; the job is failed, not left "running".
STALE_AFTER = timedelta(minutes=45)


@dataclass(frozen=True)
class Outcome:
    job_id: int | None
    status: str
    detail: str

    def __str__(self) -> str:
        return (
            f"{self.status}: {self.detail}"
            if self.job_id is None
            else (f"job {self.job_id} {self.status}: {self.detail}")
        )


@dataclass(frozen=True)
class Worker:
    conn: psycopg.Connection
    jobs: VideoJobRepository
    trades: TradeRepository
    members: MemberAliasRepository
    runs: RunRepository
    delivery: DeliveryService
    notify: Callable[[str], object]
    assets: Assets
    script_ai: Callable[[], StructuredOutputClient]
    ffmpeg: str
    ffprobe: str
    #: 8 s of voiced footage generated in about four minutes on 2026-09-10; 12 s took
    #: over twenty. The read fits: 20 words.
    seconds: int = 8
    render: Callable[..., pipeline.Job] = pipeline.render
    write_script: Callable[..., object] = generate_script
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def run_once(self) -> Outcome:
        for stale in self.jobs.fail_stale(STALE_AFTER, self.now()):
            self.notify(f"trade video job {stale} was stale and is marked failed")
        job = self.jobs.claim()
        self.conn.commit()
        if job is None:
            return Outcome(None, "idle", "no queued video jobs")
        run_id = self.runs.reserve(AGENT, TRIGGER, f"video:{job.id}:{job.attempts}")
        self.conn.commit()
        try:
            output = self._render(job.trade_id, job.trade_code)
            self.delivery.deliver_attachment(run_id, AGENT, output.name, output.read_bytes())
            self.jobs.finish(job.id, str(output))
            if run_id is not None:
                self.runs.finish(run_id, "succeeded")
            self.conn.commit()
            return Outcome(job.id, "done", str(output))
        except Exception as exc:  # noqa: BLE001 - the job records whatever broke
            self.conn.rollback()
            detail = f"{exc.__class__.__name__}: {exc}"[:300]
            self.jobs.fail(job.id, detail)
            if run_id is not None:
                self.runs.finish(run_id, "failed", error=exc.__class__.__name__)
            self.conn.commit()
            self.notify(f"trade video {job.trade_code} failed — {detail}")
            return Outcome(job.id, "failed", detail)

    def _render(self, trade_id: int, trade_code: str) -> Path:
        trade = self.trades.find_by_id(trade_id)
        if trade is None:
            raise LookupError(f"trade {trade_code} is no longer on file")
        proposal = TradeProposal(**trade["terms"])
        copy = trade_copy(proposal, party_labels(self.members.all_members()))
        read = self.write_script(self.script_ai(), copy, self.seconds)
        request = pipeline.RenderRequest(
            copy=copy,
            base="generated",
            name=trade_code,
            voiced=True,
            script=read,
            generate_seconds=self.seconds,
            music_gain_db=MUSIC_GAIN_DB,
        )
        job = self.render(
            request,
            self.assets,
            ffmpeg=self.ffmpeg,
            ffprobe=self.ffprobe,
            report=lambda line: self.notify(f"{trade_code}: {line}"),
        )
        return job.composite.output
