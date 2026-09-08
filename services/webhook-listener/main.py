"""Launch the BlueBubbles webhook listener. Supervised by launchd on the Mac mini."""
import httpx
import uvicorn
from ultimate_guillotine.config import DeliveryMode, load_settings
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


def main() -> None:
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
    allowed = {
        t.chat_guid
        for t in (targets.get(DeliveryMode.TEST), targets.get(DeliveryMode.PRODUCTION))
        if t
    }
    notifier = HermesNotifier.from_settings(settings)
    delivery = DeliveryService(
        settings, client, targets, CommittingRepo(OutboundRepository(conn), conn), notifier
    )
    registry = TriggerRegistry()
    # Agents from later plans register their triggers in this launcher next to ping_trigger.
    if settings.delivery_mode is DeliveryMode.TEST and settings.test_chat_guid:
        registry.register(ping_trigger(delivery, settings.test_chat_guid))
    processor = InboundProcessor(
        allowed,
        registry,
        CommittingRepo(ReceiptRepository(conn), conn),
        CommittingRepo(SourceMessageRepository(conn), conn),
        on_error=lambda name, exc: notifier.ops(
            f"listener trigger {name} failed: {exc.__class__.__name__}"
        ),
    )
    app = create_app(
        processor,
        CommittingRepo(HeartbeatRepository(conn), conn),
        settings.webhook_password.get_secret_value(),
    )
    uvicorn.run(
        app,
        host=settings.webhook_listen_host,
        port=settings.webhook_listen_port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
