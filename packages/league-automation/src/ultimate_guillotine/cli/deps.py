"""Shared dependency construction and run-recording helper for `ug` subcommands."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx
import psycopg

from ultimate_guillotine.ai.hermes import HermesStructuredClient
from ultimate_guillotine.ai.structured import StructuredOutputClient
from ultimate_guillotine.config import Settings, load_settings
from ultimate_guillotine.core.hermes_cli import find_hermes_binary
from ultimate_guillotine.data.database import connect
from ultimate_guillotine.data.repositories import (
    OutboundRepository,
    RunRepository,
    TargetRepository,
)
from ultimate_guillotine.messages.bluebubbles import BlueBubblesClient
from ultimate_guillotine.messages.delivery import DeliveryService
from ultimate_guillotine.ops.notify import HermesNotifier
from ultimate_guillotine.ops.transitions import transition_note

log = logging.getLogger(__name__)


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


def build_ai(deps: Deps) -> StructuredOutputClient:
    """Build the structured-output client the extraction commands call.

    The credentials live in the Hermes profile, so the only thing that can be
    missing here is the CLI itself. That is a setup problem, not a runtime
    failure: exiting with a plain message beats a traceback out of `subprocess`
    on the first extraction.
    """
    if find_hermes_binary() is None:
        raise SystemExit("hermes CLI not found")
    return HermesStructuredClient(
        deps.settings.hermes_profile_home, model=deps.settings.hermes_model
    )


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


def post_ops(notifier: HermesNotifier, text: str) -> None:
    """Post one ops note, absorbing anything Discord or Hermes does in reply.

    The note is a courtesy; the run's verdict is the fact. `HermesNotifier.send`
    already swallows a failing `hermes` invocation, but locating the binary and
    looking up the channel id happen outside that guard, and neither is a reason
    to turn a run that did its job into a `failed` one. Only the exception class
    is logged -- the note itself is right there in the caller.
    """
    try:
        notifier.ops(text)
    except Exception as exc:  # noqa: BLE001 - an undelivered note is not a failed run
        log.warning("ops note not delivered: %s", exc.__class__.__name__)


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


def run_scheduled_with_notes(
    deps: Deps,
    agent: str,
    now: datetime,
    action: Callable[[int], int],
) -> int:
    """`run_scheduled`, plus one Discord ops note when this agent's verdict changes.

    Every scheduled Sleeper job wants the same thing: run, record, and say
    something in `#guillotine-ops` only on the edges -- the first failure after a
    success, and the recovery. Three copies of that wrapper would be three places
    to get the edge cases wrong, so it lives here once.

    The previous verdict is read *before* the run, from the newest finished run of
    the same agent; `RunRepository.last_finished_status` ignores `running` rows, so
    the reservation this call is about to make cannot be mistaken for it.

    A `None` from `run_scheduled` is a deduplicated fire -- a second cron tick
    inside the same minute. Nothing ran, so nothing changed: no note, and a zero
    exit, because a duplicate is not a failure.
    """
    previous = RunRepository(deps.conn).last_finished_status(agent)

    def note(status: str) -> None:
        text = transition_note(agent, previous, status, now)
        if text:
            post_ops(deps.notifier, text)

    try:
        exit_code = run_scheduled(deps.conn, agent, now, action)
    except Exception:
        note("failed")
        raise
    if exit_code is None:
        return 0
    note("succeeded" if exit_code == 0 else "failed")
    return exit_code
