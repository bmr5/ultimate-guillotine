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

from ultimate_guillotine.agent.records import AgentAnswerRepository, AgentSessionRepository
from ultimate_guillotine.agent.session import HermesAgentClient
from ultimate_guillotine.agent.tools.source import DatabaseSource
from ultimate_guillotine.agent.trigger import FollowUpResolver, league_agent_trigger
from ultimate_guillotine.agent.worker import AgentWorker
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
    Trigger,
    TriggerRegistry,
    ping_trigger,
)
from ultimate_guillotine.messages.bluebubbles import BlueBubblesClient, InboundMessage
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


def agent_chat_guids(settings: Settings, test_target, production_target) -> tuple[str, ...]:
    """Registered delivery chats only, in deterministic factory order.

    Production keeps the test chat available. Test mode excludes the league chat;
    disabled mode excludes both. Environment GUIDs and listen rows grant no access.
    """
    if settings.delivery_mode is DeliveryMode.DISABLED:
        return ()
    targets = (test_target, production_target) if (
        settings.delivery_mode is DeliveryMode.PRODUCTION
    ) else (test_target,)
    return tuple(dict.fromkeys(target.chat_guid for target in targets if target is not None))


def build_agent_worker(
    settings: Settings,
    client,
    notifier,
    chat_guid: str,
    *,
    reconcile: bool,
) -> AgentWorker:
    """The worker on its own connection, its own delivery service, started and settled.

    Everything the worker touches lives on `worker_conn`: the snapshot reads, the
    session and answer records, the outbound reservations. The listener's own
    connection is never handed to it, so a timer-thread post and a webhook can
    never share a transaction.

    ``chat_guid`` is the factory's legacy contract, the first authorized chat,
    and nothing the worker needs: it replies to whatever chat each question came
    from. ``reconcile`` settles the runs a restart orphaned, and only the live
    listener may ask for it: `ug ingest gap-fill` builds this same processor
    while the listener is up, and a gap-fill that reconciled would mark the
    listener's in-flight run failed.
    """
    worker_conn = connect(settings)
    delivery = DeliveryService(
        settings,
        client,
        TargetRepository(worker_conn),
        CommittingRepo(OutboundRepository(worker_conn), worker_conn),
        notifier,
        commit=worker_conn.commit,
    )
    worker = AgentWorker(
        client=HermesAgentClient(
            settings.hermes_league_profile_home, model=settings.hermes_model
        ),
        source=DatabaseSource(
            worker_conn, SleeperClient(httpx.Client()), settings.sleeper_league_id
        ),
        delivery=delivery,
        notifier=notifier,
        runs=CommittingRepo(RunRepository(worker_conn), worker_conn),
        sessions=CommittingRepo(AgentSessionRepository(worker_conn), worker_conn),
        answers=CommittingRepo(AgentAnswerRepository(worker_conn), worker_conn),
    )
    if reconcile:
        worker.reconcile_startup()
    worker.start()
    return worker


def _register_league_agent(
    settings: Settings,
    conn,
    client,
    delivery,
    notifier,
    registry,
    chat_guids: tuple[str, ...],
    worker_factory: Callable[[str], AgentWorker] | None = None,
    reconcile: bool = False,
    video_matches: Callable[[InboundMessage], bool] | None = None,
) -> None:
    """Register the League Agent, or say once why it is not running.

    Disabled delivery or no registered target produces one log line. A
    missing Hermes CLI *is* a fault somebody has to fix, so it is announced once
    here rather than by failing each question in turn.

    The listener's half shares the listener's connection, and only the run
    repository is wrapped: the reservation is committed before the job is
    queued, so a redelivered webhook cannot start a second answer. The worker
    is built by ``worker_factory`` -- by default `build_agent_worker`, on a
    connection of its own -- and a test hands in a stand-in so nothing here
    connects or starts a thread.
    """
    if not chat_guids:
        log.info(
            "league agent disabled: no authorized delivery chat, mode is %s",
            settings.delivery_mode,
        )
        return
    if find_hermes_binary() is None:
        log.warning("league agent disabled: hermes CLI not found")
        notifier.ops("League Agent disabled: hermes CLI not found")
        return
    factory = worker_factory or (
        lambda guid: build_agent_worker(settings, client, notifier, guid, reconcile=reconcile)
    )
    # One queue, connection, startup and reconciliation for all authorized chats.
    worker = factory(chat_guids[0])
    resolver = FollowUpResolver(
        OutboundRepository(conn), RunRepository(conn), AgentSessionRepository(conn)
    )
    for chat_guid in chat_guids:
        registry.register(
            league_agent_trigger(
                worker=worker,
                contacts=MemberContactRepository(conn),
                commissioner_username=settings.commissioner_sleeper_username,
                members=MemberAliasRepository(conn).all_members,
                resolver=resolver,
                runs=CommittingRepo(RunRepository(conn), conn),
                delivery=delivery,
                chat_guid=chat_guid,
                video_matches=video_matches,
            )
        )


def _register_trade_registrar(
    settings: Settings,
    conn,
    delivery,
    notifier,
    registry,
    chat_guids: frozenset[str],
    listen_guids: Iterable[str] = (),
    code_prefix: str | None = None,
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
    season's real trade numbers. ``code_prefix`` overrides the mode's prefix for
    a registrar that only hears the self-test chat while production is live.

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
        TradeRepository(conn, code_prefix or code_prefix_for(settings.delivery_mode)),
        CommittingRepo(RunRepository(conn), conn),
        contacts_repo=MemberContactRepository(conn),
        sources_repo=SourceMessageRepository(conn),
        sleeper_client=SleeperClient(httpx.Client()),
        shadow_chat_hashes=frozenset(chat_guid_hash(guid) for guid in listen_guids),
    )
    registry.register(trade_trigger(registrar, chat_guids))


def _register_trade_video(conn, delivery, registry, chat_guids: frozenset[str]) -> Trigger | None:
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
    trigger = video_trigger(requests, chat_guids)
    registry.register(trigger)
    return trigger


def build_processor(
    settings: Settings,
    conn,
    client,
    delivery,
    notifier,
    *,
    agent_worker_factory: Callable[[str], AgentWorker] | None = None,
    reconcile_agent_runs: bool = False,
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

    ``agent_worker_factory`` builds one shared worker from the first authorized
    chat; the default opens a connection and starts a thread, and a test
    passes a stand-in. ``reconcile_agent_runs`` is `main()`'s alone: the live
    listener settles the runs its last restart orphaned, and a gap-fill, which
    runs beside the live listener, must never fail that listener's in-flight run.
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
    # In production the league chat is the registrar's, and the self-test chat stays a
    # rehearsal room: an alert posted there is logged under a TEST- code and answered
    # there (`DeliveryService.reply_to`), never with a real trade number. Ben
    # (2026-09-10): log a trade in the test chat, then ask for its video.
    if settings.delivery_mode is DeliveryMode.PRODUCTION and test_target is not None:
        _register_trade_registrar(
            settings,
            conn,
            delivery,
            notifier,
            registry,
            frozenset({test_target.chat_guid}),
            code_prefix="TEST",
        )
    # Requests are heard wherever alerts are, and in the self-test chat in every mode.
    # Reuse the actual registered predicate so video and Agent ownership agree.
    video_chats = trade_chat_guids(settings, production_target, listen_guids)
    if test_target is not None:
        video_chats = video_chats | {test_target.chat_guid}
    video = _register_trade_video(conn, delivery, registry, video_chats)
    _register_league_agent(
        settings,
        conn,
        client,
        delivery,
        notifier,
        registry,
        agent_chat_guids(settings, test_target, production_target),
        agent_worker_factory,
        reconcile_agent_runs,
        video_matches=video.matches if video is not None else None,
    )
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
    processor, _allowed = build_processor(
        settings, conn, client, delivery, notifier, reconcile_agent_runs=True
    )
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
