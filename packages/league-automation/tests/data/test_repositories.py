from datetime import UTC, datetime, timedelta

import pytest

from ultimate_guillotine.config import DeliveryMode
from ultimate_guillotine.data.repositories import (
    HeartbeatRepository,
    MemberAliasRepository,
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


def test_stuck_sending_lists_stale_reservations(conn) -> None:
    targets = TargetRepository(conn)
    target_id = targets.upsert(DeliveryMode.TEST, "iMessage;+;chat-test", None, "self-test")
    outbound = OutboundRepository(conn)
    oid = outbound.reserve(None, target_id, "hello", "abc")
    now = datetime.now(UTC)

    # A reserved-but-not-sending row is not stuck.
    assert outbound.stuck_sending(timedelta(seconds=-1), now) == []

    outbound.set_state(oid, "sending")
    assert outbound.stuck_sending(timedelta(minutes=10), now) == []
    assert outbound.stuck_sending(timedelta(seconds=-1), now) == [oid]

    # A finished send is no longer stuck.
    outbound.set_state(oid, "sent", bluebubbles_guid="guid-1")
    assert outbound.stuck_sending(timedelta(seconds=-1), now) == []


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


def test_member_alias_repository_replaces_and_lists_aliases(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.members (display_name) values (%s) returning id",
            ("Member01",),
        )
        member_id = cur.fetchone()[0]

    repo = MemberAliasRepository(conn)
    assert repo.replace_aliases("Member01", ["Ben", "benny"]) == 2

    members = repo.all_members()
    member = next(m for m in members if m.member_id == member_id)
    assert member.display_name == "Member01"
    assert set(member.aliases) == {"Ben", "benny"}

    assert repo.replace_aliases("Member01", ["B"]) == 1
    members = repo.all_members()
    member = next(m for m in members if m.member_id == member_id)
    assert member.aliases == ("B",)

    with pytest.raises(ValueError):
        repo.replace_aliases("Nobody", ["x"])
