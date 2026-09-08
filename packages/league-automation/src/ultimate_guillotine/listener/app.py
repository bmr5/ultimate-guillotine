import logging
import os
import secrets
from collections.abc import Callable
from typing import NoReturn

import psycopg
from fastapi import FastAPI, HTTPException, Request

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
            heartbeats.beat("listener")
            msg = parse_webhook(payload)
            if msg is None:
                return {"outcome": "ignored_event"}
            return {"outcome": processor.process(msg, msg.guid)}
        except psycopg.OperationalError as exc:
            _die_on_lost_connection(exc)

    return app
