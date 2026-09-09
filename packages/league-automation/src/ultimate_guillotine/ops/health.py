"""System health checks over heartbeats, expected runs, stuck sends, and
BlueBubbles reachability."""

from datetime import datetime, timedelta

LISTENER_STALE_AFTER = timedelta(minutes=10)
STUCK_SENDING_AFTER = timedelta(minutes=10)
STUCK_RUNNING_AFTER = timedelta(minutes=15)


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
    # A run still `running` this long after it started means an agent died
    # between reserving the run and finishing it: nothing was recorded and
    # nothing was said. `ug trades retry <guid>` re-runs a trade candidate.
    stuck_runs = runs.stale_running(STUCK_RUNNING_AFTER, now)
    if stuck_runs:
        agents = sorted({agent for agent, _key in stuck_runs})
        minutes = int(STUCK_RUNNING_AFTER.total_seconds() // 60)
        problems.append(
            f"runs stuck running > {minutes}m: {len(stuck_runs)} (agent {', '.join(agents)})"
        )
    if not client.ping():
        problems.append("BlueBubbles server is not responding to ping")
    return problems
