"""Build and launch the BlueBubbles webhook listener.

`build_processor` is factored out so `ug ingest gap-fill` can replay missed
messages through the exact same trigger pipeline the live listener uses.
"""

import logging
import threading
from collections.abc import Callable, Iterable
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
    chat_guid_hash,
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
from ultimate_guillotine.video.jobs import VideoJobRepository
from ultimate_guillotine.video.trigger import VideoRequests, code_in, video_trigger

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


def trade_chat_guids(
    settings: Settings, production_target, listen_guids: Iterable[str] = ()
) -> frozenset[str]:
    """Every chat the registrar reads trade alerts in. Empty means it does not run.

    The delivery chat comes first and is what the mode is: test mode reads the
    configured test chat, production reads the production delivery target's chat
    (where the target's identity has already been checked), `disabled` has no chat
    at all.

    ``listen_guids`` are the listen-only targets, and they are added in every mode
    that has a delivery chat -- shadow mode. Reading a chat and answering in it
    are now two different questions: the registrar hears an alert in the league
    chat and posts its answer through ``DeliveryService``, which resolves the
    destination by ``DELIVERY_MODE`` and knows nothing about this set. So in test
    mode a league alert is answered in the self-test chat, with a ``TEST-`` code,
    and the league sees nothing.

    A listen-only chat with **no** delivery chat is deliberately nothing: an agent
    that can hear but has nowhere to speak would extract trades and discard the
    answers, which is a worse thing to leave running than an agent that is off.
    """
    if settings.delivery_mode is DeliveryMode.TEST:
        delivery = settings.test_chat_guid
    elif settings.delivery_mode is DeliveryMode.PRODUCTION:
        delivery = production_target.chat_guid if production_target else None
    else:
        delivery = None
    if delivery is None:
        return frozenset()
    return frozenset({delivery, *listen_guids})


def advisor_chat_guid(settings: Settings, test_target) -> str | None:
    """The one chat the Advisor answers in: the self-test chat, and only that.

    The chat comes from the **registered** test delivery target rather than from
    `settings.test_chat_guid`, so the Advisor answers in exactly the chat the
    listener already trusts: `build_processor` builds its allowlist from the same
    rows, and a `TEST_CHAT_GUID` in the environment that no `private
    .delivery_targets` row backs would otherwise name a chat every webhook from
    it is refused in — a skill registered against a chat it can never hear from.
    No registered target means no chat, and the Advisor does not run.

    The spec keeps the Advisor in the self-test chat until Ben promotes it, and
    `private.delivery_targets` has one row per mode with no per-skill column --
    so promotion is this function returning the production target's chat, a
    deliberate reviewed change, and never a database row somebody adds by
    accident.
    """
    if settings.delivery_mode is DeliveryMode.TEST and test_target is not None:
        return test_target.chat_guid
    return None


def _register_trade_advisor(
    settings: Settings, conn, delivery, notifier, registry, chat_guid: str | None
) -> None:
    """Register the Trade Advisor, or say once why it is not running.

    Not being cleared for this delivery mode -- or having no registered
    self-test target to answer in -- is the expected state of every production
    start rather than a fault, so it is one log line and not an ops note: an ops
    note posted on every restart is one nobody reads. A missing Hermes CLI *is*
    a fault: it is a machine somebody has to fix, so it is announced once here
    rather than by failing each question in turn.

    The repositories share the listener's connection, and only the run
    repository is wrapped: the Advisor commits after each step itself, so a
    reservation is durable before the model is called and a redelivered webhook
    cannot start a second answer.
    """
    if chat_guid is None:
        log.info(
            "trade advisor disabled: registered self-test chat only, mode is %s",
            settings.delivery_mode,
        )
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
    settings: Settings,
    conn,
    delivery,
    notifier,
    registry,
    chat_guids: frozenset[str],
    listen_guids: Iterable[str] = (),
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

    The contact repository is what lets a first-person alert name its announcer:
    without loaded handles every sender is unplaceable, and `I sent X to Y` ends
    in a question rather than a trade.

    ``chat_guids`` is every chat alerts are read in and ``listen_guids`` the
    subset that is listen-only. The registrar is given the *hashes* of the second
    set, never the GUIDs: all it does with them is mark a candidate that came from
    a shadow chat, and that is not a reason to hand an agent a raw chat id.
    """
    if not chat_guids:
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
        contacts_repo=MemberContactRepository(conn),
        sources_repo=SourceMessageRepository(conn),
        sleeper_client=SleeperClient(httpx.Client()),
        shadow_chat_hashes=frozenset(chat_guid_hash(guid) for guid in listen_guids),
    )
    registry.register(trade_trigger(registrar, chat_guids))


def _register_trade_video(conn, delivery, registry, chat_guids: frozenset[str]) -> None:
    """Register the video request trigger in every chat trade alerts are read in.

    It queues work and acknowledges; the render runs in `ug video jobs run`.
    No alert chat means the registrar is off too, and a request nobody can
    hear is not worth registering.
    """
    if not chat_guids:
        log.info("trade video disabled: no chat to hear requests in")
        return
    outbound = OutboundRepository(conn)
    requests = VideoRequests(
        TradeRepository(conn),
        VideoJobRepository(conn),
        delivery,
        conn,
        code_for_outbound_guid=lambda guid: code_in(outbound.content_for_guid(guid)),
        sources=SourceMessageRepository(conn),
        members=MemberAliasRepository(conn),
    )
    registry.register(video_trigger(requests, chat_guids))


def build_processor(
    settings: Settings, conn, client, delivery, notifier
) -> tuple[InboundProcessor, set[str]]:
    """Build the trigger registry and inbound processor shared by the live listener
    and `ug ingest gap-fill`.

    Returns the processor together with the set of chat GUIDs it accepts messages
    from: the configured test and production delivery targets, plus every
    listen-only target. A listen-only chat is one the automation reads and never
    posts to, so widening the allowlist with them widens what can be *heard* and
    nothing else -- every send still goes through `DeliveryService`, which
    resolves its destination by `DELIVERY_MODE`.

    Receipts and source messages are recorded through a `CommittingRepo`, so each
    processed message commits on its own.
    """
    targets = TargetRepository(conn)
    test_target = targets.get(DeliveryMode.TEST)
    production_target = targets.get(DeliveryMode.PRODUCTION)
    listen_guids = targets.listen_chat_guids()
    allowed = {t.chat_guid for t in (test_target, production_target) if t} | set(listen_guids)
    registry = TriggerRegistry()
    # Agents from later plans register their triggers here, next to ping_trigger.
    if settings.delivery_mode is DeliveryMode.TEST and settings.test_chat_guid:
        registry.register(ping_trigger(delivery, settings.test_chat_guid))
    _register_trade_registrar(
        settings,
        conn,
        delivery,
        notifier,
        registry,
        trade_chat_guids(settings, production_target, listen_guids),
        listen_guids,
    )
    _register_trade_advisor(
        settings,
        conn,
        delivery,
        notifier,
        registry,
        advisor_chat_guid(settings, test_target),
    )
    # Requests are heard wherever alerts are, and in the self-test chat in every mode:
    # in production a request there is answered there (`DeliveryService.reply_to`), so
    # Ben can keep trying the bot out without the league seeing a thing.
    video_chats = trade_chat_guids(settings, production_target, listen_guids)
    if test_target is not None:
        video_chats = video_chats | {test_target.chat_guid}
    _register_trade_video(conn, delivery, registry, video_chats)
    processor = InboundProcessor(
        allowed,
        registry,
        CommittingRepo(ReceiptRepository(conn), conn),
        CommittingRepo(SourceMessageRepository(conn), conn),
        on_error=lambda name, exc: notifier.ops(f"trigger {name} failed: {exc.__class__.__name__}"),
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
