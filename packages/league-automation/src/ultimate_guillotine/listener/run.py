"""Build and launch the BlueBubbles webhook listener.

`build_processor` is factored out so `ug ingest gap-fill` can replay missed
messages through the exact same trigger pipeline the live listener uses.
"""

import logging
import threading
from collections.abc import Callable
from time import sleep

import httpx
import psycopg
import uvicorn

from ultimate_guillotine.advisor.pricing import PriceRepository
from ultimate_guillotine.advisor.prompt import advisor_client
from ultimate_guillotine.advisor.skill import TradeAdvisor, advisor_trigger
from ultimate_guillotine.advisor.state import SnapshotRepository
from ultimate_guillotine.ai.hermes import HermesStructuredClient
from ultimate_guillotine.config import DeliveryMode, Settings, load_settings
from ultimate_guillotine.core.hermes_cli import find_hermes_binary
from ultimate_guillotine.data.database import connect
from ultimate_guillotine.data.repositories import (
    HeartbeatRepository,
    MemberAliasRepository,
    MemberContactRepository,
    OutboundRepository,
    ReceiptRepository,
    RunRepository,
    SourceMessageRepository,
    TargetRepository,
)
from ultimate_guillotine.listener.app import _die_on_lost_connection, create_app
from ultimate_guillotine.listener.committing import CommittingRepo
from ultimate_guillotine.listener.processing import (
    InboundProcessor,
    TriggerRegistry,
    ping_trigger,
)
from ultimate_guillotine.messages.bluebubbles import BlueBubblesClient
from ultimate_guillotine.messages.delivery import DeliveryService
from ultimate_guillotine.ops.notify import HermesNotifier
from ultimate_guillotine.sleeper.client import SleeperClient
from ultimate_guillotine.sleeper.players import PlayerRepository
from ultimate_guillotine.trades.registrar import TradeRegistrar, trade_trigger
from ultimate_guillotine.trades.repository import TradeRepository, code_prefix_for

log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 120


def _heartbeat_loop(connection_factory: Callable[[], psycopg.Connection]) -> None:
    """Beat for the listener on a fixed interval, forever, on its own connection.

    Beating only on webhook receipt meant a quiet league chat looked identical to a
    dead listener: the health job reported a stale heartbeat every night and `ug ops
    doctor` failed. The connection is opened here, inside the thread, rather than
    shared with the request path or the `/healthz` probe — a rollback on either of
    those can no longer discard this thread's uncommitted heartbeat. A dead
    connection is fatal: `psycopg.OperationalError` exits the process the same way a
    dead request-path connection does, for launchd to restart. Any other failure is
    logged by exception class name only and never kills the thread — a heartbeat
    that cannot be written for some other reason is exactly the condition the health
    job is meant to notice.
    """
    try:
        conn = connection_factory()
    except psycopg.OperationalError as exc:
        _die_on_lost_connection(exc)
    except Exception as exc:  # noqa: BLE001 - only lost connection is fatal
        log.warning("listener heartbeat failed: %s", exc.__class__.__name__)
        return

    heartbeats = CommittingRepo(HeartbeatRepository(conn), conn)
    while True:
        try:
            heartbeats.beat("listener")
        except psycopg.OperationalError as exc:
            _die_on_lost_connection(exc)
        except Exception as exc:  # noqa: BLE001 - only a lost connection is fatal here
            log.warning("listener heartbeat failed: %s", exc.__class__.__name__)
        sleep(HEARTBEAT_INTERVAL_SECONDS)


def start_heartbeat_thread(
    settings: Settings,
    connection_factory: Callable[[], psycopg.Connection] | None = None,
) -> threading.Thread:
    """Start the background heartbeat as a daemon thread so it never blocks shutdown.

    Opens its own connection via `connection_factory` (default: a fresh connection
    from `settings`) instead of sharing the request-path connection.
    """
    factory = connection_factory or (lambda: connect(settings))
    thread = threading.Thread(
        target=_heartbeat_loop, args=(factory,), name="listener-heartbeat", daemon=True
    )
    thread.start()
    return thread


def _check_db(connection_factory: Callable[[], psycopg.Connection]) -> bool:
    """Probe the database on a short-lived connection of its own.

    Never touches the request-path connection, so a `/healthz` probe can no longer
    roll back another thread's uncommitted work. A lost connection here is not
    fatal — it just means the process reports itself unhealthy; nothing exits.
    """
    try:
        with connection_factory() as probe:
            probe.execute("select 1")
    except psycopg.OperationalError:
        return False
    return True


def trade_chat_guid(settings: Settings, production_target) -> str | None:
    """The one chat the registrar answers trades in, or ``None`` if there isn't one.

    Test mode answers in the configured test chat; production answers in the
    production delivery target's chat, which is where the target's identity has
    already been checked. `disabled` has no chat to answer in at all, so the
    registrar does not run.
    """
    if settings.delivery_mode is DeliveryMode.TEST:
        return settings.test_chat_guid
    if settings.delivery_mode is DeliveryMode.PRODUCTION:
        return production_target.chat_guid if production_target else None
    return None


def advisor_chat_guid(settings: Settings) -> str | None:
    """The one chat the Advisor answers in: the self-test chat, and only that.

    The spec keeps the Advisor in the self-test chat until Ben promotes it, and
    `private.delivery_targets` has one row per mode with no per-skill column --
    so promotion is this function returning the production chat, a deliberate
    reviewed change, and never a database row somebody adds by accident.

    The trusted-chat allowlist is enforced twice over: `build_processor` refuses
    every webhook whose chat is not a registered delivery target before any
    trigger runs, and the trigger this GUID is handed to narrows that again to
    the one chat named here.
    """
    if settings.delivery_mode is DeliveryMode.TEST:
        return settings.test_chat_guid
    return None


def _register_trade_advisor(
    settings: Settings, conn, delivery, notifier, registry, chat_guid: str | None
) -> None:
    """Register the Trade Advisor, or say once why it is not running.

    Not being cleared for this delivery mode is the expected state of every
    production start rather than a fault, so it is a log line and not an ops
    note -- an ops note posted on every restart is one nobody reads. A missing
    Hermes CLI *is* a fault: it is a machine somebody has to fix, so it is
    announced once here rather than by failing each question in turn.

    The repositories share the listener's connection, and only the run
    repository is wrapped: the Advisor commits after each step itself, so a
    reservation is durable before the model is called and a redelivered webhook
    cannot start a second answer.
    """
    if chat_guid is None:
        log.info("trade advisor disabled: self-test chat only, mode is %s",
                 settings.delivery_mode)
        return
    if find_hermes_binary() is None:
        log.warning("trade advisor disabled: hermes CLI not found")
        notifier.ops("Trade Advisor disabled: hermes CLI not found")
        return
    advisor = TradeAdvisor(
        settings,
        conn,
        advisor_client(settings.hermes_profile_home, model=settings.hermes_model),
        delivery,
        notifier,
        MemberContactRepository(conn),
        MemberAliasRepository(conn),
        SnapshotRepository(conn),
        PriceRepository(conn),
        CommittingRepo(RunRepository(conn), conn),
    )
    registry.register(advisor_trigger(advisor, chat_guid))


def _register_trade_registrar(
    settings: Settings, conn, delivery, notifier, registry, chat_guid: str | None
) -> None:
    """Register the Trade Registrar, or say once why it is not running.

    Without a chat to answer in, or without the Hermes CLI that carries every
    model call, the registrar cannot do its job, so the listener starts without
    it rather than failing every alert one at a time. That is a configuration
    problem someone has to fix, so it is announced in ops at startup -- once,
    here, and never again per message.

    The repositories are handed the listener's own connection: the registrar
    commits after each step itself, so the trade, its revision, and the run all
    land together rather than one commit per repository call. Only the run
    repository is wrapped, so a reservation is durable before the model is
    called and a redelivered webhook cannot start a second extraction.

    Test mode writes `TEST-` trade codes: a gate rehearsal must not consume the
    season's real trade numbers.
    """
    if chat_guid is None:
        log.warning("trade registrar disabled: no target chat for %s", settings.delivery_mode)
        notifier.ops(f"Trade Registrar disabled: no target chat for {settings.delivery_mode}")
        return
    if find_hermes_binary() is None:
        log.warning("trade registrar disabled: hermes CLI not found")
        notifier.ops("Trade Registrar disabled: hermes CLI not found")
        return
    ai = HermesStructuredClient(settings.hermes_profile_home, model=settings.hermes_model)
    registrar = TradeRegistrar(
        settings,
        conn,
        ai,
        delivery,
        notifier,
        MemberAliasRepository(conn),
        PlayerRepository(conn),
        TradeRepository(conn, code_prefix_for(settings.delivery_mode)),
        CommittingRepo(RunRepository(conn), conn),
        sources_repo=SourceMessageRepository(conn),
        sleeper_client=SleeperClient(httpx.Client()),
    )
    registry.register(trade_trigger(registrar, chat_guid))


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
    test_target = targets.get(DeliveryMode.TEST)
    production_target = targets.get(DeliveryMode.PRODUCTION)
    allowed = {t.chat_guid for t in (test_target, production_target) if t}
    registry = TriggerRegistry()
    # Agents from later plans register their triggers here, next to ping_trigger.
    if settings.delivery_mode is DeliveryMode.TEST and settings.test_chat_guid:
        registry.register(ping_trigger(delivery, settings.test_chat_guid))
    _register_trade_registrar(
        settings, conn, delivery, notifier, registry,
        trade_chat_guid(settings, production_target),
    )
    _register_trade_advisor(
        settings, conn, delivery, notifier, registry, advisor_chat_guid(settings)
    )
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
    start_heartbeat_thread(settings)

    def check_db() -> bool:
        return _check_db(lambda: connect(settings))

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
