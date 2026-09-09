from datetime import UTC, datetime

import pytest

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
        "season": 2026, "effective_week": 2, "kind": "permanent",
        "parties": [TradeParty(m1, "Member01"), TradeParty(m2, "Member02")],
        "assets": [TradeAsset("player", m1, m2, "p1", "Player Alpha", None, None, None),
                   TradeAsset("faab", m2, m1, None, None, 450, "faab", None)],
        "rental_return_condition": None, "special_terms": [], "referenced_trade_code": None,
        "source_message_guid": "g1", "evidence_excerpt": "🚨 ...",
        "prompt_version": "2026.1", "model": "m",
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
                "faab", make(conn).parties[1].member_id, make(conn).parties[0].member_id,
                None, None, 500, "faab", None,
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
