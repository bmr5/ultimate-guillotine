"""Run the history query against isolated PostgreSQL temporary tables."""

from datetime import UTC, datetime, timedelta

import pytest

from ultimate_guillotine.trades.transfers import recent_transfers_context

NOW = datetime(2026, 9, 15, 17, tzinfo=UTC)


class TempCursor:
    def __init__(self, conn):
        self.cur = conn.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cur.close()

    def execute(self, sql, params):
        # Exercise the production query unchanged except for its table namespace.
        self.cur.execute(sql.replace("public.", "pg_temp."), params)

    def fetchall(self):
        return self.cur.fetchall()


class TempConnection:
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return TempCursor(self.conn)


@pytest.fixture
def history(conn):
    for name, columns in {
        "seasons": "id int, year int",
        "members": "id int, display_name text",
        "teams": "id int, member_id int, season_id int",
        "players": "sleeper_player_id text, full_name text",
        "transactions": "id int, season_id int, kind text, occurred_at timestamptz",
        "transaction_moves": "transaction_id int, sleeper_player_id text, team_id int, action text",
        "roster_holdings": "team_id int, sleeper_player_id text",
    }.items():
        conn.execute(f"create temporary table {name} ({columns}) on commit drop")
    conn.execute("insert into pg_temp.seasons values (1, 2026), (2, 2025)")
    conn.execute(
        "insert into pg_temp.members values (1, 'Member01'), (2, 'Member02'), (3, 'Member03')"
    )
    conn.execute("insert into pg_temp.teams values (1, 1, 1), (2, 2, 1), (3, 3, 1), (4, 1, 2)")
    conn.execute("insert into pg_temp.players values ('p1', 'Player Alpha')")
    conn.execute("insert into pg_temp.roster_holdings values (2, 'p1')")
    conn.execute(
        "insert into pg_temp.transactions values (1, 1, 'trade', %s)",
        (NOW - timedelta(hours=1),),
    )
    conn.execute(
        "insert into pg_temp.transaction_moves values (1, 'p1', 1, 'drop'), (1, 'p1', 2, 'add')"
    )
    return conn, TempConnection(conn)


def test_recent_direct_trade_names_the_previous_owner_and_current_holder(history):
    _, view = history
    assert "Player Alpha: Member01 -> Member02 (current holder)" in recent_transfers_context(
        view, 2026, NOW
    )


@pytest.mark.parametrize("hours", [25, -1])
def test_old_and_future_transfers_are_excluded(history, hours):
    conn, view = history
    conn.execute(
        "update pg_temp.transactions set occurred_at = %s", (NOW - timedelta(hours=hours),)
    )
    assert recent_transfers_context(view, 2026, NOW) == ""


@pytest.mark.parametrize("kind", ["waiver", "free_agent", "commissioner"])
def test_only_direct_trades_supply_an_owner(history, kind):
    conn, view = history
    conn.execute("update pg_temp.transactions set kind = %s", (kind,))
    assert recent_transfers_context(view, 2026, NOW) == ""


def test_a_later_drop_invalidates_the_older_trade_even_if_rosters_lag(history):
    conn, view = history
    conn.execute("insert into pg_temp.transactions values (2, 1, 'free_agent', %s)", (NOW,))
    conn.execute("insert into pg_temp.transaction_moves values (2, 'p1', 2, 'drop')")
    assert recent_transfers_context(view, 2026, NOW) == ""


def test_a_later_trade_replaces_the_previous_transfer(history):
    conn, view = history
    conn.execute("insert into pg_temp.transactions values (2, 1, 'trade', %s)", (NOW,))
    conn.execute(
        "insert into pg_temp.transaction_moves values (2, 'p1', 2, 'drop'), (2, 'p1', 3, 'add')"
    )
    conn.execute("update pg_temp.roster_holdings set team_id = 3")
    pack = recent_transfers_context(view, 2026, NOW)
    assert "Player Alpha: Member02 -> Member03" in pack
    assert "Member01" not in pack


@pytest.mark.parametrize(
    "change",
    [
        "delete from pg_temp.roster_holdings",
        "update pg_temp.roster_holdings set team_id = 3",
        "insert into pg_temp.roster_holdings values (1, 'p1')",
        "delete from pg_temp.transaction_moves where action = 'drop'",
    ],
)
def test_missing_or_conflicting_evidence_is_excluded(history, change):
    conn, view = history
    conn.execute(change)
    assert recent_transfers_context(view, 2026, NOW) == ""


def test_other_seasons_do_not_conflict_with_current_ownership(history):
    conn, view = history
    conn.execute("insert into pg_temp.roster_holdings values (4, 'p1')")
    assert "Player Alpha" in recent_transfers_context(view, 2026, NOW)
    assert recent_transfers_context(view, 2025, NOW) == ""
