"""What `sleeper/transactions.py` reads off the transaction log, and what it writes.

The parsing cases are pure. The sync cases run against the real tables, because the
value of the upsert is the `sleeper_transaction_id` conflict target the ten-minute
rerun depends on.
"""

from collections import Counter
from datetime import UTC, datetime

import pytest

from ultimate_guillotine.sleeper.sync import sync_season
from ultimate_guillotine.sleeper.transactions import (
    FaabMove,
    Move,
    TransactionReport,
    load_transactions,
    sync_transactions,
)

from .conftest import LEAGUE_ID, FakeClient, load_fixture

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
TEAMS = {1: 11, 2: 22, 3: 33}

TRADE = {
    "transaction_id": "t-1",
    "type": "trade",
    "status": "complete",
    "created": 1788876037088,
    "status_updated": 1788876100000,
    "leg": 1,
    "roster_ids": [1, 2],
    "adds": {"pA": 2, "pB": 1},
    "drops": {"pA": 1, "pB": 2},
    "waiver_budget": [{"amount": 65, "sender": 1, "receiver": 2}],
    "draft_picks": [],
    "settings": None,
}
CLAIM = {
    "transaction_id": "t-2",
    "type": "waiver",
    "status": "complete",
    "created": 1789005344972,
    "status_updated": None,
    "leg": 2,
    "roster_ids": [3],
    "adds": {"pC": 3},
    "drops": {"pD": 3},
    "waiver_budget": [],
    "settings": {"waiver_bid": 12, "seq": 1},
}
FAILED_BID = {**CLAIM, "transaction_id": "t-3", "status": "failed"}
PICKUP = {
    "transaction_id": "t-4",
    "type": "free_agent",
    "status": "complete",
    "created": 1789100000000,
    "leg": 2,
    "roster_ids": [2],
    "adds": {"pE": 2},
    "drops": None,
    "waiver_budget": None,
}


def test_a_trade_yields_an_add_for_the_receiver_and_a_drop_for_the_sender() -> None:
    load = load_transactions([TRADE], TEAMS)
    (tx,) = load.transactions
    assert tx.sleeper_transaction_id == "t-1"
    assert tx.kind == "trade"
    assert tx.team_ids == [11, 22]
    assert sorted(tx.moves, key=lambda m: (m.sleeper_player_id, m.action)) == [
        Move("pA", 22, "add"),
        Move("pA", 11, "drop"),
        Move("pB", 11, "add"),
        Move("pB", 22, "drop"),
    ]


def test_faab_moves_map_roster_ids_onto_team_ids() -> None:
    (tx,) = load_transactions([TRADE], TEAMS).transactions
    assert tx.faab_moves == [FaabMove(65, 11, 22)]
    assert tx.waiver_bid is None


def test_the_week_is_sleepers_leg_and_the_time_prefers_status_updated() -> None:
    (tx,) = load_transactions([TRADE], TEAMS).transactions
    assert tx.week == 1
    assert tx.occurred_at == datetime(2026, 9, 8, 14, 1, 40, tzinfo=UTC)


def test_a_claim_keeps_its_bid_and_falls_back_to_created() -> None:
    (tx,) = load_transactions([CLAIM], TEAMS).transactions
    assert tx.kind == "waiver"
    assert tx.waiver_bid == 12
    assert tx.occurred_at == datetime(2026, 9, 10, 1, 55, 44, 972000, tzinfo=UTC)
    assert sorted(tx.moves, key=lambda m: m.action) == [
        Move("pC", 33, "add"),
        Move("pD", 33, "drop"),
    ]


def test_a_failed_bid_is_not_a_transaction() -> None:
    load = load_transactions([FAILED_BID], TEAMS)
    assert load.transactions == []
    assert (load.unknown_kinds, load.unmatched_rosters, load.malformed) == (Counter(), 0, 0)


def test_null_drops_and_null_faab_read_as_none_of_either() -> None:
    (tx,) = load_transactions([PICKUP], TEAMS).transactions
    assert tx.moves == [Move("pE", 22, "add")]
    assert tx.faab_moves == []
    assert tx.waiver_bid is None


def test_the_raw_record_is_kept_verbatim() -> None:
    (tx,) = load_transactions([TRADE], TEAMS).transactions
    assert tx.raw == TRADE


def test_an_unknown_kind_is_counted_and_skipped() -> None:
    """One new string from Sleeper must not stall the whole log."""
    load = load_transactions([{**TRADE, "type": "gift"}, PICKUP], TEAMS)
    assert [t.sleeper_transaction_id for t in load.transactions] == ["t-4"]
    assert load.unknown_kinds == Counter({"gift": 1})


def test_a_roster_with_no_team_row_is_counted_and_skipped() -> None:
    load = load_transactions([TRADE, PICKUP], {2: 22})
    assert [t.sleeper_transaction_id for t in load.transactions] == ["t-4"]
    assert load.unmatched_rosters == 1


def test_a_record_missing_its_id_week_or_time_is_malformed() -> None:
    load = load_transactions(
        [
            {**TRADE, "transaction_id": None},
            {**TRADE, "leg": None},
            {**TRADE, "created": None, "status_updated": None},
            "not a record",
        ],
        TEAMS,
    )
    assert load.transactions == []
    assert load.malformed == 4


class RecordingClient(FakeClient):
    """The shared fake, remembering which weeks were asked for."""

    def __init__(self) -> None:
        super().__init__()
        self.weeks: list[int] = []

    def get_transactions(self, league_id: str, week: int) -> list[dict]:
        self.weeks.append(week)
        return super().get_transactions(league_id, week)


def _fixture_moves() -> int:
    return sum(
        len(t.get("adds") or {}) + len(t.get("drops") or {})
        for t in load_fixture("transactions_2026_w1.json")
        if t["status"] == "complete"
    )


def _rows(conn) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            "select sleeper_transaction_id, kind, week, occurred_at, team_ids, faab_moves, "
            "waiver_bid from public.transactions order by sleeper_transaction_id"
        )
        return cur.fetchall()


def test_a_sync_writes_the_week_and_its_moves(conn, season_id, team_id) -> None:
    sync_season(FakeClient(), conn, year=2026, league_id=LEAGUE_ID)
    client = RecordingClient()
    report = sync_transactions(client, conn, LEAGUE_ID, season_id, [1], NOW)
    assert report == TransactionReport(transactions=8, moves=_fixture_moves(), weeks=[1])
    assert client.weeks == [1]
    rows = _rows(conn)
    assert len(rows) == 8
    trade = next(r for r in rows if r[0] == "1403051427646935040")
    assert trade[1:3] == ("trade", 1)
    assert set(trade[4]) == {team_id(1), team_id(16)}
    assert trade[5] == [{"amount": 65, "from_team_id": team_id(1), "to_team_id": team_id(16)}]
    with conn.cursor() as cur:
        cur.execute(
            "select m.sleeper_player_id, m.team_id, m.action from public.transaction_moves m "
            "join public.transactions t on t.id = m.transaction_id "
            "where t.sleeper_transaction_id = %s order by 1, 3",
            ("1403051427646935040",),
        )
        assert cur.fetchall() == [
            ("12534", team_id(16), "add"),
            ("12534", team_id(1), "drop"),
            ("9487", team_id(1), "add"),
            ("9487", team_id(16), "drop"),
        ]


def test_a_rerun_rewrites_the_same_rows_and_moves_only_the_stamp(conn, season_id) -> None:
    sync_season(FakeClient(), conn, year=2026, league_id=LEAGUE_ID)
    sync_transactions(FakeClient(), conn, LEAGUE_ID, season_id, [1], NOW)
    before = _rows(conn)
    later = datetime(2026, 9, 10, 12, 10, tzinfo=UTC)
    sync_transactions(FakeClient(), conn, LEAGUE_ID, season_id, [1], later)
    assert _rows(conn) == before
    with conn.cursor() as cur:
        cur.execute("select distinct synced_at from public.transactions")
        assert cur.fetchall() == [(later,)]
        cur.execute("select count(*) from public.transaction_moves")
        assert cur.fetchone()[0] == _fixture_moves()


def test_an_empty_week_writes_nothing_and_is_not_a_failure(conn, season_id) -> None:
    sync_season(FakeClient(), conn, year=2026, league_id=LEAGUE_ID)
    client = RecordingClient()
    report = sync_transactions(client, conn, LEAGUE_ID, season_id, [1, 2], NOW)
    assert client.weeks == [1, 2]
    assert (report.transactions, report.weeks) == (8, [1, 2])


def test_a_season_with_no_teams_refuses_before_fetching(conn, season_id) -> None:
    client = RecordingClient()
    with pytest.raises(ValueError, match="run ug sleeper sync"):
        sync_transactions(client, conn, LEAGUE_ID, season_id, [1], NOW)
    assert client.weeks == []
