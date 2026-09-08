"""`ug ops` subcommands: heartbeat, health, audit-runs, sync-expected-runs,
self-test, doctor, register-webhook, fingerprint."""

import argparse
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

from ultimate_guillotine.cli.deps import build_delivery, build_deps, run_scheduled
from ultimate_guillotine.config import DeliveryMode, load_settings
from ultimate_guillotine.data.database import connect
from ultimate_guillotine.data.repositories import (
    ExpectedRun,
    ExpectedRunRepository,
    HeartbeatRepository,
    OutboundRepository,
    RunRepository,
    TargetRepository,
)
from ultimate_guillotine.messages.bluebubbles import BlueBubblesClient
from ultimate_guillotine.messages.delivery import DeliveryDisabled, TargetMismatch
from ultimate_guillotine.messages.fingerprint import participant_fingerprint
from ultimate_guillotine.ops.health import LISTENER_STALE_AFTER, check_health
from ultimate_guillotine.ops.notify import HermesNotifier

log = logging.getLogger(__name__)

PYTHON_VERSION = (3, 12)


def register(subparsers) -> None:
    parser = subparsers.add_parser("ops", help="operational commands")
    ops_sub = parser.add_subparsers(dest="command", required=True)

    heartbeat = ops_sub.add_parser("heartbeat", help="record a heartbeat for a component")
    heartbeat.add_argument("--component", required=True)
    heartbeat.set_defaults(handler=cmd_heartbeat)

    health = ops_sub.add_parser("health", help="report health problems")
    health.add_argument(
        "--escalate", action="store_true", help="also post problems to the alerts channel"
    )
    health.set_defaults(handler=cmd_health)

    audit = ops_sub.add_parser("audit-runs", help="report jobs that missed their schedule")
    audit.set_defaults(handler=cmd_audit_runs)

    sync = ops_sub.add_parser(
        "sync-expected-runs", help="load the expected job schedule from a YAML file"
    )
    sync.add_argument("path")
    sync.set_defaults(handler=cmd_sync_expected_runs)

    self_test = ops_sub.add_parser("self-test", help="send and verify a self-test message")
    self_test.add_argument(
        "--crash-after-send", action="store_true", help="simulate a crash after sending"
    )
    self_test.set_defaults(handler=cmd_self_test)

    doctor = ops_sub.add_parser("doctor", help="run environment diagnostics")
    doctor.set_defaults(handler=cmd_doctor)

    register_webhook = ops_sub.add_parser(
        "register-webhook", help="register the webhook URL with BlueBubbles"
    )
    register_webhook.set_defaults(handler=cmd_register_webhook)

    fingerprint = ops_sub.add_parser(
        "fingerprint", help="print a chat's current participant fingerprint"
    )
    fingerprint.add_argument("--chat-guid", required=True)
    fingerprint.set_defaults(handler=cmd_fingerprint)


def cmd_heartbeat(args: argparse.Namespace) -> int:
    deps = build_deps()
    HeartbeatRepository(deps.conn).beat(args.component)
    deps.conn.commit()
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    now = datetime.now(UTC)
    try:
        deps = build_deps()
    except Exception as exc:  # noqa: BLE001 - never let a health check crash Hermes
        message = f"Health check could not start: {exc.__class__.__name__}"
        print(message)
        if args.escalate:
            settings = None
            try:
                settings = load_settings()
            except Exception:  # noqa: BLE001 - settings themselves are what failed
                settings = None
            if settings is not None:
                HermesNotifier.from_settings(settings).alerts(message)
        return 0

    conn = deps.conn

    def action(run_id: int) -> int:
        problems = check_health(
            now,
            HeartbeatRepository(conn),
            RunRepository(conn),
            ExpectedRunRepository(conn),
            deps.client,
            OutboundRepository(conn),
        )
        for problem in problems:
            print(problem)
        if args.escalate and problems:
            deps.notifier.alerts("\n".join(problems))
        return 0

    return run_scheduled(conn, "health", now, action)


def cmd_audit_runs(args: argparse.Namespace) -> int:
    deps = build_deps()
    conn = deps.conn
    now = datetime.now(UTC)

    def action(run_id: int) -> int:
        expected = ExpectedRunRepository(conn)
        runs = RunRepository(conn)
        for job in expected.all():
            last = runs.last_started(job.agent)
            if last is None:
                print(f"Missed: Expected job {job.job_name} has never run")
                continue
            age = int((now - last).total_seconds() // 60)
            if age > job.max_gap_minutes:
                print(
                    f"Missed: Expected job {job.job_name} last ran {age} minutes ago "
                    f"(limit {job.max_gap_minutes})"
                )
        return 0

    return run_scheduled(conn, "run-audit", now, action)


def cmd_sync_expected_runs(args: argparse.Namespace) -> int:
    deps = build_deps()
    data = yaml.safe_load(Path(args.path).read_text())
    rows = [
        ExpectedRun(job["name"], job["agent"], int(job["max_gap_minutes"]), job["schedule"])
        for job in (data or {}).get("jobs", [])
    ]
    ExpectedRunRepository(deps.conn).replace_all(rows)
    deps.conn.commit()
    print(f"synced {len(rows)} expected runs")
    return 0


def cmd_self_test(args: argparse.Namespace) -> int:
    deps = build_deps()
    settings = deps.settings
    if settings.delivery_mode is DeliveryMode.PRODUCTION:
        print("self-test refuses to run in production mode")
        return 2
    if settings.delivery_mode is DeliveryMode.DISABLED:
        print("self-test refuses to run when delivery is disabled")
        return 2

    conn = deps.conn
    now = datetime.now(UTC)
    delivery = build_delivery(deps, crash_after_send=args.crash_after_send)

    # Minute precision, so a retry inside the same minute reproduces the content hash
    # of the reservation a crashed attempt left behind and reconciles against it
    # instead of sending twice.
    content = f"Self-test {now:%Y-%m-%dT%H:%M}"

    def action(run_id: int) -> int:
        try:
            result = delivery.deliver(run_id, "self-test", content)
        except (DeliveryDisabled, TargetMismatch) as exc:
            print(str(exc))
            return 1
        print(f"{result.status} {result.outbound_id}")
        return 0

    # Per-attempt run key: the self-test is invoked by hand, and Gate 0 re-runs it
    # deliberately within the same minute, so it must never be skipped as a duplicate.
    return run_scheduled(
        conn,
        "self-test",
        now,
        action,
        trigger="cli",
        idempotency_key=f"self-test:{now:%Y%m%dT%H%M%S%f}",
    )


def cmd_doctor(args: argparse.Namespace) -> int:
    results: list[tuple[str, bool, str]] = []
    state: dict[str, object] = {}

    def check(name: str, fn) -> None:
        try:
            fn()
            results.append((name, True, ""))
        except Exception as exc:  # noqa: BLE001
            results.append((name, False, exc.__class__.__name__))

    def need(key: str):
        value = state.get(key)
        if value is None:
            raise RuntimeError(f"{key} unavailable")
        return value

    def check_python() -> None:
        if (sys.version_info.major, sys.version_info.minor) != PYTHON_VERSION:
            raise RuntimeError("python is not 3.12")

    def check_settings() -> None:
        state["settings"] = load_settings()

    def check_delivery_mode() -> None:
        settings = need("settings")
        if settings.delivery_mode is DeliveryMode.DISABLED:
            raise RuntimeError("delivery mode is disabled")

    def check_database() -> None:
        settings = need("settings")
        conn = connect(settings)
        with conn.cursor() as cur:
            cur.execute("select 1")
        state["conn"] = conn

    def check_bluebubbles_ping() -> None:
        settings = need("settings")
        client = BlueBubblesClient(
            settings.bluebubbles_server_url,
            settings.bluebubbles_password.get_secret_value()
            if settings.bluebubbles_password
            else "",
            httpx.Client(),
        )
        state["client"] = client
        if not client.ping():
            raise RuntimeError("no pong from BlueBubbles")

    def check_bluebubbles_info() -> None:
        client = need("client")
        info = client.server_info()
        if not isinstance(info, dict):
            raise TypeError("server_info did not return a dict")

    def check_delivery_target() -> None:
        settings = need("settings")
        conn = need("conn")
        target = TargetRepository(conn).get(settings.delivery_mode)
        if target is None:
            raise RuntimeError("no delivery target row for the configured mode")
        expected_guid = (
            settings.test_chat_guid
            if settings.delivery_mode is DeliveryMode.TEST
            else settings.production_chat_guid
        )
        if target.chat_guid != expected_guid:
            raise RuntimeError("stored target does not match the configured chat")

    def check_listener_healthz() -> None:
        settings = need("settings")
        response = httpx.get(
            f"http://{settings.webhook_listen_host}:{settings.webhook_listen_port}/healthz",
            timeout=5.0,
        )
        if response.status_code != 200:
            raise RuntimeError(f"unexpected status {response.status_code}")

    def check_listener_heartbeat() -> None:
        conn = need("conn")
        stale = HeartbeatRepository(conn).stale(LISTENER_STALE_AFTER, datetime.now(UTC))
        if "listener" in stale:
            raise RuntimeError("listener heartbeat is stale")

    def check_hermes_send() -> None:
        settings = need("settings")
        home = str(Path(settings.hermes_profile_home).expanduser())
        result = subprocess.run(
            ["hermes", "send", "--list"],
            env={**os.environ, "HERMES_HOME": home},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"hermes exited {result.returncode}")

    for name, fn in (
        ("python", check_python),
        ("settings", check_settings),
        ("delivery_mode", check_delivery_mode),
        ("database", check_database),
        ("bluebubbles_ping", check_bluebubbles_ping),
        ("bluebubbles_info", check_bluebubbles_info),
        ("delivery_target", check_delivery_target),
        ("listener_healthz", check_listener_healthz),
        ("listener_heartbeat", check_listener_heartbeat),
        ("hermes_send", check_hermes_send),
    ):
        check(name, fn)

    conn = state.get("conn")
    if conn is not None:
        try:
            conn.rollback()
            conn.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("failed to close doctor connection: %s", exc.__class__.__name__)

    ok = True
    for name, passed, reason in results:
        if passed:
            print(f"PASS {name}")
        else:
            ok = False
            print(f"FAIL {name}: {reason}")
    return 0 if ok else 1


def cmd_register_webhook(args: argparse.Namespace) -> int:
    deps = build_deps()
    settings = deps.settings
    password = settings.webhook_password.get_secret_value() if settings.webhook_password else ""
    url = (
        f"http://{settings.webhook_listen_host}:{settings.webhook_listen_port}"
        f"/bluebubbles-webhook?password={password}"
    )
    deps.client.ensure_webhook(url)
    print("webhook registered")
    return 0


def cmd_fingerprint(args: argparse.Namespace) -> int:
    deps = build_deps()
    participants = deps.client.chat_participants(args.chat_guid)
    print(participant_fingerprint(participants))
    return 0
