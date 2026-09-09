import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest

from ultimate_guillotine.config import DeliveryMode
from ultimate_guillotine.data.repositories import (
    HeartbeatRepository,
    MemberAliasRepository,
    OutboundRepository,
    ReceiptRepository,
    RunRepository,
    SeasonRepository,
    SourceMessage,
    SourceMessageRepository,
    TargetRepository,
    chat_guid_hash,
)
from ultimate_guillotine.trades.names import normalize_name


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


def test_member_alias_repository_stores_normalized_aliases_once(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.members (display_name) values (%s) returning id",
            ("Member07",),
        )
        member_id = cur.fetchone()[0]

    repo = MemberAliasRepository(conn)
    # "Big Ben" and "big  ben!" normalize to the same alias and collapse to one row.
    assert repo.replace_aliases("Member07", ["Big Ben", "big  ben!", "Benny"]) == 2

    with conn.cursor() as cur:
        cur.execute(
            "select alias, alias_normalized from private.member_aliases where member_id = %s",
            (member_id,),
        )
        rows = cur.fetchall()

    assert {row[1] for row in rows} == {"big ben", "benny"}
    for alias, alias_normalized in rows:
        assert alias_normalized == normalize_name(alias)


def test_member_alias_repository_rejects_an_alias_owned_by_another_member(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("insert into public.members (display_name) values ('Member08')")
        cur.execute("insert into public.members (display_name) values ('Member09')")

    repo = MemberAliasRepository(conn)
    assert repo.replace_aliases("Member08", ["Shared"]) == 1

    # The savepoint keeps the failed insert from poisoning the test transaction.
    with pytest.raises(ValueError, match="already belongs to another member"), conn.transaction():
        repo.replace_aliases("Member09", ["shared"])


def test_repositories_do_not_import_the_http_client() -> None:
    """The persistence layer must not drag ``httpx`` (and the Sleeper client) in."""
    code = (
        "import sys\n"
        "import ultimate_guillotine.data.repositories  # noqa: F401\n"
        "assert 'httpx' not in sys.modules, sorted(sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_stale_running_reports_runs_that_never_finished(conn) -> None:
    """A run left in `running` is an agent that died mid-flight; the health job
    names the agent so a human knows what to re-run."""
    runs = RunRepository(conn)
    stuck = runs.reserve("trade-registrar", "webhook", "trade:stuck")
    fresh = runs.reserve("trade-registrar", "webhook", "trade:fresh")
    done = runs.reserve("trade-registrar", "webhook", "trade:done")
    runs.finish(done, "succeeded")
    with conn.cursor() as cur:
        cur.execute(
            "update private.agent_runs set started_at = now() - interval '30 minutes' "
            "where id in (%s, %s)",
            (stuck, done),
        )

    now = datetime.now(UTC)
    assert runs.stale_running(timedelta(minutes=15), now) == [("trade-registrar", "trade:stuck")]
    assert runs.stale_running(timedelta(hours=2), now) == []
    assert fresh is not None


def test_last_finished_status_ignores_this_run_and_other_agents(conn) -> None:
    """The transition notes ask "did the answer change?", so the run in flight --
    still `running` -- must not be the answer, and neither must another agent's."""
    runs = RunRepository(conn)
    assert runs.last_finished_status("projections-sync") is None

    runs.finish(runs.reserve("projections-sync", "cron", "proj:1"), "succeeded")
    assert runs.last_finished_status("projections-sync") == "succeeded"

    runs.finish(runs.reserve("projections-sync", "cron", "proj:2"), "failed")
    runs.finish(runs.reserve("sleeper-sync", "cron", "sleeper:1"), "succeeded")
    runs.reserve("projections-sync", "cron", "proj:3")  # the run asking the question
    assert runs.last_finished_status("projections-sync") == "failed"
    assert runs.last_finished_status("sleeper-sync") == "succeeded"


def test_season_repository_reads_the_newest_season(conn) -> None:
    repo = SeasonRepository(conn)
    # Years past anything the local database is seeded with, so "newest" is ours.
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into public.seasons (year, sleeper_league_id, rules_version)
            values (2521, 'l', 'v1'), (2522, 'l', 'v1')
            on conflict (year) do update set rules_version = excluded.rules_version
            """
        )
    assert repo.current() == 2522
    assert repo.exists(2521) is True
    assert repo.exists(1999) is False


def test_find_repost_matches_the_same_text_from_another_message(conn) -> None:
    """A repost is the same text in the same chat under a different GUID; the
    message's own row is always there, so it has to be excluded by GUID."""
    repo = SourceMessageRepository(conn)
    sent = datetime.now(UTC)
    chat = chat_guid_hash("iMessage;+;chat-test")
    original = SourceMessage(
        source_guid="g1", chat_guid_hash=chat, sender_hash=None, direction="inbound",
        sent_at=sent - timedelta(days=1), content_fingerprint="fp-1", excerpt="🚨 ...",
        trigger_name="trade-registrar",
    )
    repo.upsert(original)
    repo.upsert(
        SourceMessage(
            source_guid="g2", chat_guid_hash=chat, sender_hash=None, direction="inbound",
            sent_at=sent, content_fingerprint="fp-1", excerpt="🚨 ...",
            trigger_name="trade-registrar",
        )
    )
    repo.upsert(
        SourceMessage(
            source_guid="g3", chat_guid_hash=chat, sender_hash=None, direction="outbound",
            sent_at=sent, content_fingerprint="fp-bot", excerpt="🚨 ...", trigger_name=None,
        )
    )
    since = sent - timedelta(days=7)

    assert repo.find_repost(chat, "fp-1", "g2", since) is True
    assert repo.find_repost(chat, "fp-other", "g2", since) is False
    assert repo.find_repost(chat_guid_hash("other-chat"), "fp-1", "g2", since) is False
    # The only other row with this text is older than the window.
    assert repo.find_repost(chat, "fp-1", "g2", sent - timedelta(hours=1)) is False
    # The bot's own posts are outbound and never count as a repost.
    assert repo.find_repost(chat, "fp-bot", "g9", since) is False


def test_replace_aliases_leaves_the_old_rows_when_one_alias_is_taken(conn) -> None:
    """The delete and the inserts are one savepoint: a conflict must not strand
    the member with no aliases, or leave the transaction unusable."""
    repo = MemberAliasRepository(conn)
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.members (display_name) values ('Alias One'), ('Alias Two')"
        )
    repo.replace_aliases("Alias One", ["keeper"])
    repo.replace_aliases("Alias Two", ["taken"])

    with pytest.raises(ValueError, match="already belongs to another member"):
        repo.replace_aliases("Alias One", ["fresh", "taken"])

    aliases = {m.display_name: m.aliases for m in repo.all_members()}
    assert aliases["Alias One"] == ("keeper",)


def test_replace_aliases_publishes_the_first_alias_as_the_nickname(conn) -> None:
    """The board and the Concierge label owners by nickname, so exactly one alias
    becomes public. The rest stay in private.member_aliases, which anon cannot read."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.members (display_name) values ('Nick One') returning id"
        )
        member_id = cur.fetchone()[0]
    repo = MemberAliasRepository(conn)

    repo.replace_aliases("Nick One", ["Benny", "The Hammer"])

    with conn.cursor() as cur:
        cur.execute("select nickname from public.members where id = %s", (member_id,))
        assert cur.fetchone()[0] == "Benny"
    member = next(m for m in repo.all_members() if m.member_id == member_id)
    assert member.has_nickname is True


def test_a_member_with_no_aliases_has_a_null_nickname(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.members (display_name) values ('Nick Two') returning id"
        )
        member_id = cur.fetchone()[0]
    repo = MemberAliasRepository(conn)

    repo.replace_aliases("Nick Two", ["Solo"])
    repo.replace_aliases("Nick Two", [])

    with conn.cursor() as cur:
        cur.execute("select nickname from public.members where id = %s", (member_id,))
        assert cur.fetchone()[0] is None
    member = next(m for m in repo.all_members() if m.member_id == member_id)
    assert member.has_nickname is False


def test_a_rejected_alias_load_leaves_the_old_nickname_in_place(conn) -> None:
    """The nickname write shares the savepoint with the alias rows: a load that
    collides on somebody else's alias must not strand a member half-renamed."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.members (display_name) values ('Nick Three'), ('Nick Four')"
        )
    repo = MemberAliasRepository(conn)
    repo.replace_aliases("Nick Three", ["keeper"])
    repo.replace_aliases("Nick Four", ["taken"])

    with pytest.raises(ValueError, match="already belongs to another member"):
        repo.replace_aliases("Nick Three", ["fresh", "taken"])

    with conn.cursor() as cur:
        cur.execute(
            "select nickname from public.members where display_name = 'Nick Three'"
        )
        assert cur.fetchone()[0] == "keeper"
