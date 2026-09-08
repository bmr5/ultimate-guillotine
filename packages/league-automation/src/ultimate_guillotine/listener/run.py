"""Build and launch the BlueBubbles webhook listener.

`build_processor` is factored out so `ug ingest gap-fill` can replay missed
messages through the exact same trigger pipeline the live listener uses.
"""

import logging
import threading
from time import sleep

import httpx
import uvicorn

from ultimate_guillotine.config import DeliveryMode, Settings, load_settings
from ultimate_guillotine.data.database import connect
from ultimate_guillotine.data.repositories import (
    HeartbeatRepository,
    OutboundRepository,
    ReceiptRepository,
    SourceMessageRepository,
    TargetRepository,
)
from ultimate_guillotine.listener.app import create_app
from ultimate_guillotine.listener.committing import CommittingRepo
from ultimate_guillotine.listener.processing import (
    InboundProcessor,
    TriggerRegistry,
    ping_trigger,
)
from ultimate_guillotine.messages.bluebubbles import BlueBubblesClient
from ultimate_guillotine.messages.delivery import DeliveryService
from ultimate_guillotine.ops.notify import HermesNotifier

log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 120


def _heartbeat_loop(heartbeats) -> None:
    """Beat for the listener on a fixed interval, forever.

    Beating only on webhook receipt meant a quiet league chat looked identical to a
    dead listener: the health job reported a stale heartbeat every night and `ug ops
    doctor` failed. Failures here are logged by exception class name only and never
    kill the thread — a heartbeat that cannot be written is exactly the condition the
    health job is meant to notice.
    """
    while True:
        try:
            heartbeats.beat("listener")
        except Exception as exc:  # noqa: BLE001 - a heartbeat must never crash the listener
            log.warning("listener heartbeat failed: %s", exc.__class__.__name__)
        sleep(HEARTBEAT_INTERVAL_SECONDS)


def start_heartbeat_thread(heartbeats) -> threading.Thread:
    """Start the background heartbeat as a daemon thread so it never blocks shutdown."""
    thread = threading.Thread(
        target=_heartbeat_loop, args=(heartbeats,), name="listener-heartbeat", daemon=True
    )
    thread.start()
    return thread


def build_processor(
    settings: Settings, conn, client, delivery, notifier
) -> tuple[InboundProcessor, set[str]]:
    """Build the trigger registry and inbound processor shared by the live listener
    and `ug ingest gap-fill`.

    Returns the processor together with the set of chat GUIDs it accepts messages
    from (the configured test and production delivery targets). Receipts and source
    messages are recorded through a `CommittingRepo`, so each processed message
    commits on its own.
    """
    targets = TargetRepository(conn)
    allowed = {
        t.chat_guid
        for t in (targets.get(DeliveryMode.TEST), targets.get(DeliveryMode.PRODUCTION))
        if t
    }
    registry = TriggerRegistry()
    # Agents from later plans register their triggers here, next to ping_trigger.
    if settings.delivery_mode is DeliveryMode.TEST and settings.test_chat_guid:
        registry.register(ping_trigger(delivery, settings.test_chat_guid))
    processor = InboundProcessor(
        allowed,
        registry,
        CommittingRepo(ReceiptRepository(conn), conn),
        CommittingRepo(SourceMessageRepository(conn), conn),
        on_error=lambda name, exc: notifier.ops(
            f"trigger {name} failed: {exc.__class__.__name__}"
        ),
    )
    return processor, allowed


def main() -> None:
    """Launch the BlueBubbles webhook listener. Supervised by launchd on the Mac mini."""
    settings = load_settings()
    if not settings.webhook_password or not settings.bluebubbles_password:
        raise SystemExit("WEBHOOK_PASSWORD and BLUEBUBBLES_PASSWORD are required")
    conn = connect(settings)
    client = BlueBubblesClient(
        settings.bluebubbles_server_url,
        settings.bluebubbles_password.get_secret_value(),
        httpx.Client(),
    )
    targets = TargetRepository(conn)
    notifier = HermesNotifier.from_settings(settings)
    delivery = DeliveryService(
        settings,
        client,
        targets,
        CommittingRepo(OutboundRepository(conn), conn),
        notifier,
        commit=conn.commit,
    )
    processor, _allowed = build_processor(settings, conn, client, delivery, notifier)
    heartbeats = CommittingRepo(HeartbeatRepository(conn), conn)
    start_heartbeat_thread(heartbeats)

    def check_db() -> bool:
        with conn.cursor() as cur:
            cur.execute("select 1")
            ok = cur.fetchone() is not None
        conn.rollback()
        return ok

    app = create_app(
        processor,
        heartbeats,
        settings.webhook_password.get_secret_value(),
        check_db=check_db,
    )
    uvicorn.run(
        app,
        host=settings.webhook_listen_host,
        port=settings.webhook_listen_port,
        log_level="warning",
    )
