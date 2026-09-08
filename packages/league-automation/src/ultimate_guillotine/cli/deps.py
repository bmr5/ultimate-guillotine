"""Shared dependency construction and run-recording helper for `ug` subcommands."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx
import psycopg

from ultimate_guillotine.config import Settings, load_settings
from ultimate_guillotine.data.database import connect
from ultimate_guillotine.data.repositories import (
    OutboundRepository,
    RunRepository,
    TargetRepository,
)
from ultimate_guillotine.messages.bluebubbles import BlueBubblesClient
from ultimate_guillotine.messages.delivery import DeliveryService
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


def build_delivery(deps: Deps, crash_after_send: bool = False) -> DeliveryService:
    """Build the delivery service every `ug` subcommand sends through.

    The connection is not autocommit, so `deps.conn.commit` is handed to the service
    as its commit hook: without it the reservation, the `sending` transition, and the
    send itself would all sit in one uncommitted transaction, and a crash after the
    send would lose the reservation the retry needs in order to reconcile.
    """
    return DeliveryService(
        deps.settings,
        deps.client,
        TargetRepository(deps.conn),
        OutboundRepository(deps.conn),
        deps.notifier,
        crash_after_send=crash_after_send,
        commit=deps.conn.commit,
    )


def run_scheduled(
    conn: psycopg.Connection,
    agent: str,
    now: datetime,
    action: Callable[[int], int],
    trigger: str = "cron",
    idempotency_key: str | None = None,
) -> int | None:
    """Reserve a run for `agent` at this UTC minute, run `action(run_id)`, and finish it.

    `idempotency_key` defaults to one key per agent per UTC minute, which is what a
    scheduled job wants: a second cron fire inside the same minute is a duplicate.
    Commands a human re-runs on purpose (the self-test after a forced crash) pass a
    per-attempt key instead, so the retry actually runs.

    Returns `None` immediately, recording nothing further, when that idempotency key
    was already reserved (idempotency key collision) — `action` is not called.
    Otherwise finishes the run (`succeeded` when `action` returns 0, `failed` otherwise),
    commits the connection once, and returns `action`'s exit code. If `action` raises, the
    run is finished `failed`, the connection is committed, and the exception is re-raised.
    """
    runs = RunRepository(conn)
    key = idempotency_key or f"{agent}:{now:%Y%m%dT%H%M}"
    run_id = runs.reserve(agent, trigger, key)
    if run_id is None:
        return None
    try:
        exit_code = action(run_id)
    except Exception as exc:
        runs.finish(run_id, "failed", error=exc.__class__.__name__)
        conn.commit()
        raise
    runs.finish(run_id, "succeeded" if exit_code == 0 else "failed")
    conn.commit()
    return exit_code
