from datetime import UTC, datetime, timedelta

from ultimate_guillotine.config import DeliveryMode
from ultimate_guillotine.data.repositories import (
    HeartbeatRepository,
    OutboundRepository,
    ReceiptRepository,
    RunRepository,
    TargetRepository,
)


def test_reserve_run_is_idempotent(conn) -> None:
    runs = RunRepository(conn)
    first = runs.reserve("self-test", "cli", "key-1")
    second = runs.reserve("self-test", "cli", "key-1")
    assert first is not None
    assert second is None


def test_receipt_records_once(conn) -> None:
    receipts = ReceiptRepository(conn)
    assert receipts.record("evt-1", "processed") is True
    assert receipts.record("evt-1", "processed") is False


def test_outbound_pending_sending_lookup(conn) -> None:
    targets = TargetRepository(conn)
    target_id = targets.upsert(DeliveryMode.TEST, "iMessage;+;chat-test", None, "self-test")
    outbound = OutboundRepository(conn)
    oid = outbound.reserve(None, target_id, "hello", "abc")
    assert outbound.pending_sending(target_id, "abc") is None
    outbound.set_state(oid, "sending")
    assert outbound.pending_sending(target_id, "abc").id == oid


def test_stale_heartbeats(conn) -> None:
    beats = HeartbeatRepository(conn)
    beats.beat("listener")
    now = datetime.now(UTC)
    assert beats.stale(timedelta(minutes=5), now) == []
    assert beats.stale(timedelta(seconds=-1), now) == ["listener"]
