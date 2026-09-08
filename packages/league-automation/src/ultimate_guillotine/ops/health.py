"""System health checks over heartbeats, expected runs, and BlueBubbles reachability."""

from datetime import datetime, timedelta

LISTENER_STALE_AFTER = timedelta(minutes=10)


def check_health(now: datetime, heartbeats, runs, expected, client) -> list[str]:
    """Return one human-readable problem line per issue found; empty when healthy."""
    problems: list[str] = []
    for component in heartbeats.stale(LISTENER_STALE_AFTER, now):
        problems.append(f"Heartbeat for {component} is stale")
    for job in expected.all():
        last = runs.last_started(job.agent)
        if last is None:
            problems.append(f"Expected job {job.job_name} has never run")
            continue
        age = int((now - last).total_seconds() // 60)
        if age > job.max_gap_minutes:
            problems.append(
                f"Expected job {job.job_name} last ran {age} minutes ago "
                f"(limit {job.max_gap_minutes})"
            )
    if not client.ping():
        problems.append("BlueBubbles server is not responding to ping")
    return problems
