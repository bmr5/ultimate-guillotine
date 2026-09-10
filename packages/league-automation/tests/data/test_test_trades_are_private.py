"""`TEST-` trades never reach the web (skipped without TEST_DATABASE_URL).

The web app reads as the anonymous role, so the public read policies are what
hide a rehearsal trade from the board and the history pages. The automation's
own role still sees it, or `ug trades rescind TEST-…` could never find it.
"""

import psycopg
import pytest


@pytest.fixture
def two_trades(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("select id from public.seasons order by id limit 1")
        row = cur.fetchone()
        if row is None:
            pytest.skip("no season in the test database")
        season_id = row[0]
        ids = {}
        for code in ("TEST-2099-001", "T-2099-001"):
            cur.execute(
                "insert into public.trades (season_id, trade_code) values (%s, %s) returning id",
                (season_id, code),
            )
            ids[code] = cur.fetchone()[0]
            cur.execute(
                "insert into public.trade_revisions (trade_id, revision, terms) values (%s, 1, '{}')",
                (ids[code],),
            )
            cur.execute(
                """
                insert into public.league_events
                    (season_id, week, event_type, occurred_at, payload, idempotency_key)
                values (%s, 1, 'trade', now(), %s::jsonb, %s)
                """,
                (season_id, f'{{"trade_code": "{code}"}}', f"policy-test:{code}"),
            )
    return ids


def _as_role(conn, role: str, sql: str, params=()) -> list:
    with conn.cursor() as cur:
        try:
            cur.execute(f"set local role {role}")
        except psycopg.errors.InsufficientPrivilege:
            pytest.skip(f"the test database's user may not become {role}")
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.execute("reset role")


def test_the_web_never_sees_a_test_trade(conn, two_trades) -> None:
    codes = _as_role(
        conn, "anon", "select trade_code from public.trades where trade_code like '%%-2099-%%'"
    )
    assert codes == [("T-2099-001",)]
    revisions = _as_role(
        conn,
        "anon",
        "select count(*) from public.trade_revisions where trade_id = %s",
        (two_trades["TEST-2099-001"],),
    )
    assert revisions == [(0,)]
    events = _as_role(
        conn,
        "authenticated",
        "select payload->>'trade_code' from public.league_events"
        " where idempotency_key like 'policy-test:%%' order by 1",
    )
    assert events == [("T-2099-001",)]


def test_the_automation_still_sees_it(conn, two_trades) -> None:
    codes = _as_role(
        conn,
        "automation_worker",
        "select trade_code from public.trades where trade_code like '%%-2099-%%' order by 1",
    )
    assert codes == [("T-2099-001",), ("TEST-2099-001",)]
