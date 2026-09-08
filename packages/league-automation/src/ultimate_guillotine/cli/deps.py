"""Shared dependency construction and run-recording helper for `ug` subcommands."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx
import psycopg

from ultimate_guillotine.config import Settings, load_settings
from ultimate_guillotine.data.database import connect
from ultimate_guillotine.data.repositories import RunRepository
from ultimate_guillotine.messages.bluebubbles import BlueBubblesClient
from ultimate_guillotine.ops.notify import HermesNotifier


@dataclass
class Deps:
    settings: Settings
    conn: psycopg.Connection
    client: BlueBubblesClient
    notifier: HermesNotifier


def build_deps() -> Deps:
    """Build the settings, database connection, BlueBubbles client, and Hermes
    notifier that most `ug` subcommands need."""
    settings = load_settings()
    conn = connect(settings)
    client = BlueBubblesClient(
        settings.bluebubbles_server_url,
        settings.bluebubbles_password.get_secret_value() if settings.bluebubbles_password else "",
        httpx.Client(),
    )
    notifier = HermesNotifier.from_settings(settings)
    return Deps(settings=settings, conn=conn, client=client, notifier=notifier)


def run_scheduled(
    conn: psycopg.Connection, agent: str, now: datetime, action: Callable[[int], int]
) -> int:
    """Reserve a run for `agent` at this UTC minute, run `action(run_id)`, and finish it.

    Returns 0 immediately, recording nothing further, when a run for this agent at this
    minute was already reserved (idempotency key collision). Otherwise finishes the run
    (`succeeded` when `action` returns 0, `failed` otherwise), commits the connection once,
    and returns `action`'s exit code. If `action` raises, the run is finished `failed`,
    the connection is committed, and the exception is re-raised.
    """
    runs = RunRepository(conn)
    run_id = runs.reserve(agent, "cron", f"{agent}:{now:%Y%m%dT%H%M}")
    if run_id is None:
        return 0
    try:
        exit_code = action(run_id)
    except Exception as exc:
        runs.finish(run_id, "failed", error=exc.__class__.__name__)
        conn.commit()
        raise
    runs.finish(run_id, "succeeded" if exit_code == 0 else "failed")
    conn.commit()
    return exit_code
