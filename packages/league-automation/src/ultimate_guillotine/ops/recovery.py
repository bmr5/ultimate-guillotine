"""Bounded local recovery and persistent health notification state."""

import fcntl
import json
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

BLUEBUBBLES_APP = Path("/Applications/BlueBubbles.app")
COOLDOWN_SECONDS = 15 * 60
MAX_ATTEMPTS = 3


@contextmanager
def health_state(profile_home):
    """Serialize checks across processes; replace the state file atomically."""
    path = Path(profile_home).expanduser() / "health-state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(path.read_text()) if path.exists() else {}

        def save():
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state))
            temporary.replace(path)

        try:
            yield state, save
        finally:
            save()


def recover_bluebubbles(client, server_url, state, save, now, *, runner=None, sleep=None):
    """Open a stopped local app only. Never terminate it or retry a message."""
    runner = runner or subprocess.run
    sleep = sleep or time.sleep
    if client.ping():
        state.pop("bluebubbles", None)
        return None
    endpoint = urlparse(server_url)
    if sys.platform != "darwin" or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return None
    if not BLUEBUBBLES_APP.is_dir():
        return "BlueBubbles recovery unavailable: application is missing."
    recovery = state.setdefault("bluebubbles", {"attempts": 0})
    if recovery["attempts"] >= MAX_ATTEMPTS:
        return "BlueBubbles recovery stopped after 3 attempts; manual review required."
    if now.timestamp() - recovery.get("last_attempt", 0) < COOLDOWN_SECONDS:
        return None
    try:
        process = runner(["/usr/bin/pgrep", "-x", "BlueBubbles"], capture_output=True, timeout=5)
        if process.returncode != 1:
            # Zero means running; any other status means the check itself failed.
            return "BlueBubbles recovery skipped: could not confirm the application has stopped."
        recovery["attempts"] += 1
        recovery["last_attempt"] = now.timestamp()
        save()  # A crash after opening must still count toward the retry budget.
        result = runner(
            ["/usr/bin/open", "-g", "-j", "-a", str(BLUEBUBBLES_APP)],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            return "BlueBubbles automatic launch failed."
        for _ in range(10):
            sleep(2)
            if client.ping():
                state.pop("bluebubbles", None)
                return "BlueBubbles automatically reopened; connection verified."
        return "BlueBubbles launched but is not responding yet."
    except (OSError, subprocess.SubprocessError):
        return "BlueBubbles automatic recovery failed."


def issue_key(problem):
    """Ignore changing ages and run timestamps, but retain issue identities."""
    problem = re.sub(r" at \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC$", "", problem)
    return re.sub(r"last ran \d+ minutes ago", "last ran beyond schedule", problem)


def report_changes(problems, state, send, recovery_note=None, *, incomplete=False):
    """Advance notification state only after successful delivery."""
    current = {issue_key(p): p for p in problems}
    previous = state.get("reported_issues", {})
    if incomplete:
        current = {**previous, **current}
    added = current.keys() - previous.keys()
    resolved = previous.keys() - current.keys()
    lines = [current[k] for k in sorted(added)]
    lines.extend(f"Resolved: {k}" for k in sorted(resolved))
    if recovery_note and recovery_note != state.get("reported_recovery"):
        lines.append(recovery_note)
    if lines and not send("\n".join(lines)):
        return False
    state["reported_issues"] = current
    if recovery_note:
        state["reported_recovery"] = recovery_note
    elif "bluebubbles" not in state:
        state.pop("reported_recovery", None)
    return True
