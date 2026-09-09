import logging
import os
import secrets
import threading
from collections.abc import Callable
from typing import NoReturn

import psycopg
from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from ultimate_guillotine.messages.bluebubbles import parse_webhook

log = logging.getLogger(__name__)


def _die_on_lost_connection(exc: psycopg.OperationalError) -> NoReturn:
    """Leave the process for launchd to restart.

    The listener holds one long-lived connection; once it is gone every later request
    fails the same way and nothing in-process can mend it. Exiting non-zero hands the
    restart to launchd's KeepAlive, which reconnects. Only the exception class name is
    logged — the message can carry the connection string.
    """
    log.error("listener lost its database connection: %s", exc.__class__.__name__)
    os._exit(1)


def create_app(
    processor,
    heartbeats,
    webhook_password: str,
    check_db: Callable[[], bool] | None = None,
) -> FastAPI:
    """Build the listener's HTTP app.

    `check_db`, when given, is what makes /healthz mean "this process can still
    reach Supabase" rather than only "this process is still answering HTTP".
    """
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    # Every repository the processor touches shares one psycopg connection, and
    # `CommittingRepo` commits or rolls back that whole connection per call. Work runs
    # off the event loop so /healthz stays responsive, but it must stay single-flight:
    # two overlapping webhooks on one connection would interleave commits and defeat
    # the registrar's step-by-step commit boundaries.
    single_flight = threading.Lock()

    def process_serialized(msg, event_id: str) -> str:
        with single_flight:
            heartbeats.beat("listener")
            return processor.process(msg, event_id)

    @app.get("/healthz")
    def healthz() -> dict:
        try:
            healthy = check_db is None or check_db()
        except psycopg.OperationalError as exc:
            _die_on_lost_connection(exc)
        if not healthy:
            raise HTTPException(status_code=503)
        return {"ok": True}

    @app.post("/bluebubbles-webhook")
    async def webhook(request: Request) -> dict:
        supplied = request.query_params.get("password") or request.headers.get("x-password") or ""
        if not secrets.compare_digest(supplied, webhook_password):
            raise HTTPException(status_code=401)
        payload = await request.json()
        try:
            msg = parse_webhook(payload)
            if msg is None:
                with single_flight:
                    heartbeats.beat("listener")
                return {"outcome": "ignored_event"}
            # `process` is entirely blocking -- a database round trip and, for a
            # trade candidate, a Hermes subprocess that can take the better part of a
            # minute. Running it on the event loop would stop this worker answering
            # anything at all, /healthz included, for that whole time.
            return {"outcome": await run_in_threadpool(process_serialized, msg, msg.guid)}
        except psycopg.OperationalError as exc:
            _die_on_lost_connection(exc)

    return app
