"""Sender-to-member mapping over the hashed handles in `private.member_contacts`.

The whole table is hashes: the Advisor has to know whose "my roster" it is
looking at without anybody ever writing an Apple handle down. These tests pin
both halves of that -- the digest matches what the listener already stores in
`private.source_messages.sender_hash`, and no raw handle reaches a column.
"""

import hashlib

import pytest

from ultimate_guillotine.data.repositories import MemberContactRepository, handle_hash

# sha256("+15555550100"), a fake but well-formed E.164 number, computed once and
# written down. `handle_hash` normalizes before hashing; if that normalization
# ever changes shape, every `private.source_messages.sender_hash` already stored
# stops matching, and this literal is what says so out loud.
PINNED_E164_DIGEST = "0cbf019479241f66c9c60d39e69e06989f108bc47da5b938a87045a615cad4a4"


def _member(conn, name: str, nickname: str | None = None) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.members (display_name, nickname) values (%s, %s) returning id",
            (name, nickname),
        )
        return cur.fetchone()[0]


def test_handle_hash_matches_the_listener_sender_hash() -> None:
    """Both sides of the match are computed here from `hashlib` directly, so
    this fails if either implementation drifts rather than agreeing with itself."""
    from ultimate_guillotine.listener.processing import _sender_hash

    expected = hashlib.sha256(b"+15555550100").hexdigest()
    assert handle_hash("+15555550100") == expected
    assert _sender_hash("+15555550100") == expected
    assert len(expected) == 64


def test_handle_hash_of_a_plain_e164_number_is_pinned() -> None:
    assert handle_hash("+15555550100") == PINNED_E164_DIGEST


def test_handle_hash_ignores_how_a_phone_number_was_typed() -> None:
    """The commissioner types handles by hand. A digest does not forgive a space,
    so the normalization has to, or half the file silently maps nobody."""
    assert handle_hash(" +1 (555) 555-0100 ") == PINNED_E164_DIGEST
    assert handle_hash("+1-555-555.0100") == PINNED_E164_DIGEST
    assert handle_hash("+15555550100") == PINNED_E164_DIGEST


def test_handle_hash_ignores_the_case_of_an_email_handle() -> None:
    assert handle_hash("Someone@Example.com") == handle_hash("someone@example.com")
    assert handle_hash(" someone@example.com ") == handle_hash("someone@example.com")
    assert handle_hash("someone@example.com") == hashlib.sha256(b"someone@example.com").hexdigest()


def test_handle_hash_keeps_two_different_numbers_apart() -> None:
    assert handle_hash("+15555550100") != handle_hash("+15555550101")


def test_replace_handles_stores_only_hashes_and_resolves_a_sender(conn) -> None:
    _member(conn, "Member01", nickname="Benny")
    repo = MemberContactRepository(conn)
    assert repo.replace_handles("Member01", [handle_hash("+15555550100")]) == 1
    found = repo.member_for_handle_hash(handle_hash("+15555550100"))
    assert found is not None and found.display_name == "Member01"
    # Task 9 addresses the resolved member by the label the board already shows.
    assert found.nickname == "Benny"
    with conn.cursor() as cur:
        cur.execute("select handle_hash, alias from private.member_contacts")
        digest, alias = cur.fetchone()
        assert digest == hashlib.sha256(b"+15555550100").hexdigest() and alias is None


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


def test_a_handle_typed_with_formatting_still_resolves_a_stored_sender(conn) -> None:
    """The end-to-end point of normalizing: a handle loaded as a human wrote it
    matches the E.164 `sender_hash` the listener stores for that same person."""
    from ultimate_guillotine.listener.processing import _sender_hash

    _member(conn, "Member01")
    repo = MemberContactRepository(conn)
    repo.replace_handles("Member01", [handle_hash("(555) 555-0100")])
    assert repo.member_for_handle_hash(_sender_hash("+15555550100")) is None
    repo.replace_handles("Member01", [handle_hash(" +1 (555) 555-0100 ")])
    found = repo.member_for_handle_hash(_sender_hash("+15555550100"))
    assert found is not None and found.display_name == "Member01"
