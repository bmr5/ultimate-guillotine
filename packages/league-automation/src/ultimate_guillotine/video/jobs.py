"""The queue of requested trade videos.

A voiced render takes twenty minutes, so the listener never renders in line: a
request becomes a row in ``private.video_jobs`` and ``ug video jobs run``
claims the next one, renders it, and delivers the file. One open job per trade:
asking twice does not spend twice.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg

OPEN = ("queued", "running")

_COLUMNS = """
    id, trade_id, trade_code, status, requested_guid, created_at, started_at, finished_at,
    attempts, output_path, error
"""


@dataclass(frozen=True)
class VideoJob:
    id: int
    trade_id: int
    trade_code: str
    status: str
    requested_guid: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    attempts: int
    output_path: str | None
    error: str | None


def _job(row: tuple) -> VideoJob:
    return VideoJob(*row)


class VideoJobRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def enqueue(
        self, trade_id: int, trade_code: str, requested_guid: str | None
    ) -> tuple[int, bool]:
        """Queue a video for a trade; ``(job id, True)`` when this call created
        it, ``(job id, False)`` when one was already queued or running."""
        with self._conn.cursor() as cur:
            cur.execute(
                "select id from private.video_jobs where trade_id = %s and status = any(%s)"
                " order by id limit 1",
                (trade_id, list(OPEN)),
            )
            row = cur.fetchone()
            if row:
                return int(row[0]), False
            cur.execute(
                "insert into private.video_jobs (trade_id, trade_code, requested_guid)"
                " values (%s, %s, %s) returning id",
                (trade_id, trade_code, requested_guid),
            )
            return int(cur.fetchone()[0]), True

    def claim(self) -> VideoJob | None:
        """Take the oldest queued job, marking it running; ``None`` when idle.
        ``skip locked`` keeps two workers off the same job."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                update private.video_jobs
                   set status = 'running', started_at = now(), attempts = attempts + 1
                 where id = (
                    select id from private.video_jobs where status = 'queued'
                     order by id limit 1 for update skip locked
                 )
                returning {_COLUMNS}
                """
            )
            row = cur.fetchone()
            return _job(row) if row else None

    def finish(self, job_id: int, output_path: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "update private.video_jobs set status = 'done', finished_at = now(),"
                " output_path = %s, error = null where id = %s",
                (output_path, job_id),
            )

    def fail(self, job_id: int, error: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "update private.video_jobs set status = 'failed', finished_at = now(),"
                " error = %s where id = %s",
                (error[:500], job_id),
            )

    def get(self, job_id: int) -> VideoJob | None:
        with self._conn.cursor() as cur:
            cur.execute(f"select {_COLUMNS} from private.video_jobs where id = %s", (job_id,))
            row = cur.fetchone()
            return _job(row) if row else None

    def list_recent(self, limit: int = 10) -> list[VideoJob]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"select {_COLUMNS} from private.video_jobs order by id desc limit %s", (limit,)
            )
            return [_job(row) for row in cur.fetchall()]

    def fail_stale(self, older_than: timedelta, now: datetime) -> list[int]:
        """Running jobs older than ``older_than`` are a worker that died mid-render;
        mark them failed so the next request is not told a video is on its way."""
        with self._conn.cursor() as cur:
            cur.execute(
                "update private.video_jobs set status = 'failed', finished_at = %s,"
                " error = 'stale: the worker did not finish' where status = 'running'"
                " and started_at < %s returning id",
                (now, now - older_than),
            )
            return [int(row[0]) for row in cur.fetchall()]
