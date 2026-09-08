from datetime import UTC, datetime, timedelta

from ultimate_guillotine.config import DeliveryMode
from ultimate_guillotine.data.repositories import (
    HeartbeatRepository,
    OutboundRepository,
    ReceiptRepository,
    RunRepository,
    SourceMessage,
    SourceMessageRepository,
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


def test_source_message_composite_key_collision(conn) -> None:
    sources = SourceMessageRepository(conn)
    now = datetime.now(UTC)

    # Insert first message with source_guid="guid1"
    msg1 = SourceMessage(
        source_guid="guid1",
        chat_guid_hash="chat_hash1",
        sender_hash="sender1",
        direction="inbound",
        sent_at=now,
        content_fingerprint="fingerprint1",
        excerpt="hello",
        trigger_name=None,
    )
    result1 = sources.upsert(msg1)
    assert result1 is True

    # Insert second message with different source_guid but same composite key
    # (chat_guid_hash, content_fingerprint, sent_at)
    msg2 = SourceMessage(
        source_guid="guid2",
        chat_guid_hash="chat_hash1",
        sender_hash="sender2",
        direction="inbound",
        sent_at=now,
        content_fingerprint="fingerprint1",
        excerpt="hello",
        trigger_name=None,
    )
    # This should return False without raising UniqueViolation
    result2 = sources.upsert(msg2)
    assert result2 is False
