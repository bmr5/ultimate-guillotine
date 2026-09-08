"""System health checks over heartbeats, expected runs, stuck sends, and
BlueBubbles reachability."""

from datetime import datetime, timedelta

LISTENER_STALE_AFTER = timedelta(minutes=10)
STUCK_SENDING_AFTER = timedelta(minutes=10)


def check_health(now: datetime, heartbeats, runs, expected, client, outbound) -> list[str]:
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
    # A row still in `sending` long after its reservation means a send reached the
    # Messages boundary without a recorded outcome: it needs a human to look.
    for outbound_id in outbound.stuck_sending(STUCK_SENDING_AFTER, now):
        problems.append(f"Outbound message #{outbound_id} stuck in sending")
    if not client.ping():
        problems.append("BlueBubbles server is not responding to ping")
    return problems
