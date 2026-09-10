from datetime import UTC, datetime

import pytest

from ultimate_guillotine.trades.fingerprint import trade_context_key
from ultimate_guillotine.trades.models import TradeAsset, TradeParty, TradeProposal
from ultimate_guillotine.trades.repository import TradeRepository


def make(conn, **overrides) -> TradeProposal:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into public.members (display_name)
            values ('Member01'), ('Member02')
            on conflict do nothing
            """
        )
        cur.execute(
            """
            select id from public.members
            where display_name in ('Member01', 'Member02')
            order by display_name
            """
        )
        m1, m2 = [r[0] for r in cur.fetchall()]
        cur.execute(
            """
            insert into public.seasons (year, sleeper_league_id, rules_version)
            values (2026, 'league-1', 'v1')
            on conflict (year) do update set rules_version = excluded.rules_version
            """
        )
    base = {
        "season": 2026,
        "effective_week": 2,
        "kind": "permanent",
        "parties": [TradeParty(m1, "Member01"), TradeParty(m2, "Member02")],
        "assets": [
            TradeAsset("player", m1, m2, "p1", "Player Alpha", None, None, None),
            TradeAsset("faab", m2, m1, None, None, 450, "faab", None),
        ],
        "rental_return_condition": None,
        "special_terms": [],
        "referenced_trade_code": None,
        "source_message_guid": "g1",
        "evidence_excerpt": "🚨 ...",
        "prompt_version": "2026.1",
        "model": "m",
    }
    base.update(overrides)
    return TradeProposal(**base)


def test_accept_creates_then_detects_duplicate_and_revision(conn) -> None:
    repo = TradeRepository(conn)
    first = repo.accept(make(conn))
    assert first.status == "created" and first.trade_code == "T-2026-001" and first.revision == 1
    dup = repo.accept(make(conn, source_message_guid="g2", evidence_excerpt="repost"))
    assert dup.status == "duplicate" and dup.trade_id == first.trade_id
    amended = make(
        conn,
        source_message_guid="g3",
        assets=[
            make(conn).assets[0],
            TradeAsset(
                "faab",
                make(conn).parties[1].member_id,
                make(conn).parties[0].member_id,
                None,
                None,
                500,
                "faab",
                None,
            ),
        ],
    )
    revised = repo.accept(amended)
    assert revised.status == "revised" and revised.revision == 2
    assert revised.trade_id == first.trade_id
    assert revised.previous_terms["assets"][1]["amount"] == 450
    current = repo.find_by_code("T-2026-001")
    assert current["terms"]["assets"][1]["amount"] == 500 and current["status"] == "accepted"


def test_rescind_marks_trade_and_writes_event(conn) -> None:
    repo = TradeRepository(conn)
    created = repo.accept(make(conn))
    assert repo.rescind(created.trade_code, "g9", datetime.now(UTC)) is True
    assert repo.find_by_code(created.trade_code)["status"] == "rescinded"
    with conn.cursor() as cur:
        cur.execute(
            "select count(*) from public.league_events where event_type = 'trade_rescinded'"
        )
        assert cur.fetchone()[0] == 1
    assert repo.rescind("T-2026-999", "g9", datetime.now(UTC)) is False


def test_accept_raises_without_season(conn) -> None:
    repo = TradeRepository(conn)
    with pytest.raises(LookupError, match="No season row for 1999"):
        repo.accept(make(conn, season=1999))


def test_reannounced_rescinded_trade_gets_new_code(conn) -> None:
    repo = TradeRepository(conn)
    first = repo.accept(make(conn))
    assert first.trade_code == "T-2026-001"
    assert repo.rescind(first.trade_code, "g9", datetime.now(UTC)) is True
    again = repo.accept(make(conn, source_message_guid="g2"))
    assert again.status == "created"
    assert again.trade_code == "T-2026-002"
    assert again.trade_id != first.trade_id
    assert repo.find_by_code("T-2026-001")["status"] == "rescinded"
    assert repo.find_by_code("T-2026-002")["status"] == "accepted"
    with conn.cursor() as cur:
        cur.execute(
            """
            select payload->>'trade_code' from public.league_events
            where event_type = 'trade'
            order by payload->>'trade_code'
            """
        )
        assert [row[0] for row in cur.fetchall()] == ["T-2026-001", "T-2026-002"]


def test_list_recent_orders_newest_first_and_honours_limit(conn) -> None:
    repo = TradeRepository(conn)
    other = make(conn)
    first = repo.accept(other)
    second = repo.accept(
        make(
            conn,
            source_message_guid="g4",
            assets=[
                TradeAsset(
                    "player",
                    other.parties[0].member_id,
                    other.parties[1].member_id,
                    "p2",
                    "Player Beta",
                    None,
                    None,
                    None,
                ),
                other.assets[1],
            ],
        )
    )
    assert second.status == "created" and second.trade_code == "T-2026-002"
    recent = repo.list_recent()
    assert [row["trade_code"] for row in recent[:2]] == [second.trade_code, first.trade_code]
    assert [row["trade_code"] for row in repo.list_recent(limit=1)] == [second.trade_code]


def test_find_by_context_tracks_accepted_trades(conn) -> None:
    repo = TradeRepository(conn)
    proposal = make(conn)
    created = repo.accept(proposal)
    context = trade_context_key(proposal)
    assert repo.find_by_context(context) == created.trade_id
    assert repo.rescind(created.trade_code, "g9", datetime.now(UTC)) is True
    assert repo.find_by_context(context) is None


def test_accept_recovers_from_concurrent_fingerprint_insert(conn, monkeypatch) -> None:
    repo = TradeRepository(conn)
    first = repo.accept(make(conn))
    real_duplicate = TradeRepository._duplicate
    calls = {"n": 0}

    def blind_first_lookup(self, fingerprint, cur=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return real_duplicate(self, fingerprint, cur)

    monkeypatch.setattr(TradeRepository, "_duplicate", blind_first_lookup)
    again = repo.accept(make(conn, source_message_guid="g5"))
    assert again.status == "duplicate"
    assert again.trade_id == first.trade_id
    assert again.trade_code == first.trade_code
    # More than the one blinded lookup: the recovery branch re-read the row.
    assert calls["n"] > 1


def payment(conn, amount: int, guid: str):
    """A FAAB-only payment: no player asset, so nothing to key a context on."""
    base = make(conn)
    return make(
        conn,
        kind="payment",
        source_message_guid=guid,
        assets=[
            TradeAsset(
                "faab",
                base.parties[0].member_id,
                base.parties[1].member_id,
                None,
                None,
                amount,
                "faab",
                None,
            )
        ],
    )


def test_a_second_payment_between_the_same_pair_is_a_new_trade(conn) -> None:
    """Two payments between the same two people share season and parties and have
    no player to tell them apart: keying only on those would file the second as a
    revision of the first."""
    repo = TradeRepository(conn)
    first = repo.accept(payment(conn, 20, "g1"))
    second = repo.accept(payment(conn, 35, "g2"))
    assert first.status == "created" and first.trade_code == "T-2026-001"
    assert second.status == "created" and second.trade_code == "T-2026-002"
    assert second.trade_id != first.trade_id


def test_a_correction_after_the_window_is_a_new_trade(conn) -> None:
    """The same players days later is a new deal, not an amendment of the old one."""
    repo = TradeRepository(conn)
    first = repo.accept(make(conn))
    amended = make(
        conn,
        source_message_guid="g3",
        assets=[
            make(conn).assets[0],
            TradeAsset(
                "faab",
                make(conn).parties[1].member_id,
                make(conn).parties[0].member_id,
                None,
                None,
                500,
                "faab",
                None,
            ),
        ],
    )
    inside = repo.accept(amended)
    assert inside.status == "revised" and inside.trade_id == first.trade_id

    with conn.cursor() as cur:
        cur.execute(
            "update public.trade_revisions set created_at = now() - interval '4 days' "
            "where trade_id = %s",
            (first.trade_id,),
        )
    later = repo.accept(
        make(
            conn,
            source_message_guid="g4",
            assets=[
                make(conn).assets[0],
                TradeAsset(
                    "faab",
                    make(conn).parties[1].member_id,
                    make(conn).parties[0].member_id,
                    None,
                    None,
                    600,
                    "faab",
                    None,
                ),
            ],
        )
    )
    assert later.status == "created" and later.trade_code == "T-2026-002"
    assert later.trade_id != first.trade_id


def test_find_by_context_ignores_trades_older_than_the_window(conn) -> None:
    repo = TradeRepository(conn)
    proposal = make(conn)
    created = repo.accept(proposal)
    context = trade_context_key(proposal)
    assert repo.find_by_context(context) == created.trade_id
    with conn.cursor() as cur:
        cur.execute(
            "update public.trade_revisions set created_at = now() - interval '4 days' "
            "where trade_id = %s",
            (created.trade_id,),
        )
    assert repo.find_by_context(context) is None
    assert repo.find_by_context(context, within_hours=200) == created.trade_id


def test_code_prefixes_are_counted_independently(conn) -> None:
    """Gate traffic writes `TEST-` codes so it never consumes a real trade number."""
    live = TradeRepository(conn)
    gate = TradeRepository(conn, code_prefix="TEST")
    assert live.accept(make(conn)).trade_code == "T-2026-001"
    assert gate.accept(payment(conn, 20, "g2")).trade_code == "TEST-2026-001"
    assert live.accept(payment(conn, 35, "g3")).trade_code == "T-2026-002"
    assert gate.accept(payment(conn, 50, "g4")).trade_code == "TEST-2026-002"
