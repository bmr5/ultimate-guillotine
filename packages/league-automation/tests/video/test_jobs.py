"""`private.video_jobs` against the local database (skipped without TEST_DATABASE_URL)."""

from datetime import UTC, datetime, timedelta

from ultimate_guillotine.video.jobs import VideoJobRepository


def test_enqueue_claim_finish(conn) -> None:
    repo = VideoJobRepository(conn)
    job_id, created = repo.enqueue(501, "T-2026-501", "reply-1")
    assert created
    again, created_again = repo.enqueue(501, "T-2026-501", "reply-2")
    assert (again, created_again) == (job_id, False)

    job = repo.claim()
    assert job is not None and job.id == job_id
    assert (job.status, job.attempts, job.trade_code, job.requested_guid) == (
        "running",
        1,
        "T-2026-501",
        "reply-1",
    )
    assert job.started_at is not None
    assert repo.claim() is None

    repo.finish(job_id, "data/media/renders/T-2026-501.mp4")
    done = repo.get(job_id)
    assert done.status == "done" and done.output_path.endswith("T-2026-501.mp4")
    assert done.finished_at is not None
    # A finished job no longer blocks a new request for the same trade.
    assert repo.enqueue(501, "T-2026-501", "reply-3")[1] is True


def test_fail_records_the_reason_and_list_recent_is_newest_first(conn) -> None:
    repo = VideoJobRepository(conn)
    first, _ = repo.enqueue(601, "T-2026-601", None)
    second, _ = repo.enqueue(602, "T-2026-602", None)
    repo.claim()
    repo.fail(first, "HiggsfieldError: job failed")
    assert repo.get(first).error == "HiggsfieldError: job failed"
    assert [j.id for j in repo.list_recent(2)] == [second, first]


def test_stale_running_jobs_are_failed(conn) -> None:
    repo = VideoJobRepository(conn)
    job_id, _ = repo.enqueue(701, "T-2026-701", None)
    repo.claim()
    later = datetime.now(UTC) + timedelta(hours=2)
    assert repo.fail_stale(timedelta(minutes=45), later) == [job_id]
    assert repo.get(job_id).status == "failed"
    assert repo.fail_stale(timedelta(minutes=45), later) == []
