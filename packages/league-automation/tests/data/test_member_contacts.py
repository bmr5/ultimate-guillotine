"""Sender-to-member mapping over the hashed handles in `private.member_contacts`.

The whole table is hashes: the Advisor has to know whose "my roster" it is
looking at without anybody ever writing an Apple handle down. These tests pin
both halves of that -- the digest matches what the listener already stores in
`private.source_messages.sender_hash`, and no raw handle reaches a column.
"""

import pytest

from ultimate_guillotine.data.repositories import MemberContactRepository, handle_hash


def _member(conn, name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.members (display_name) values (%s) returning id", (name,)
        )
        return cur.fetchone()[0]


def test_handle_hash_matches_the_listener_sender_hash() -> None:
    from ultimate_guillotine.listener.processing import _sender_hash

    assert handle_hash("+15555550100") == _sender_hash("+15555550100")
    assert len(handle_hash("+15555550100")) == 64


def test_replace_handles_stores_only_hashes_and_resolves_a_sender(conn) -> None:
    _member(conn, "Member01")
    repo = MemberContactRepository(conn)
    assert repo.replace_handles("Member01", [handle_hash("+15555550100")]) == 1
    found = repo.member_for_handle_hash(handle_hash("+15555550100"))
    assert found is not None and found.display_name == "Member01"
    with conn.cursor() as cur:
        cur.execute("select handle_hash, alias from private.member_contacts")
        digest, alias = cur.fetchone()
        assert digest == handle_hash("+15555550100") and alias is None


def test_replace_handles_is_wholesale_and_unknown_senders_resolve_to_none(conn) -> None:
    _member(conn, "Member01")
    repo = MemberContactRepository(conn)
    repo.replace_handles("Member01", [handle_hash("a"), handle_hash("b")])
    assert repo.replace_handles("Member01", [handle_hash("b")]) == 1
    assert repo.member_for_handle_hash(handle_hash("a")) is None
    assert repo.member_for_handle_hash(handle_hash("b")) is not None
    assert repo.counts() == [("Member01", 1)]


def test_a_handle_claimed_by_another_member_is_refused(conn) -> None:
    _member(conn, "Member01")
    _member(conn, "Member02")
    repo = MemberContactRepository(conn)
    repo.replace_handles("Member01", [handle_hash("a")])
    with pytest.raises(ValueError):
        repo.replace_handles("Member02", [handle_hash("a")])
    assert repo.member_for_handle_hash(handle_hash("a")).display_name == "Member01"


def test_unknown_member_is_refused(conn) -> None:
    with pytest.raises(ValueError, match="unknown member"):
        MemberContactRepository(conn).replace_handles("Nobody", [handle_hash("a")])
