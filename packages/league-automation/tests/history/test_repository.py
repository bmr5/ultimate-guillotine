"""The two upserts, against the local stack. `conn` rolls back, so these leave nothing."""

import os
from datetime import UTC, datetime

import psycopg
import pytest

from ultimate_guillotine.history.models import CatalogRow, SeasonResultRow
from ultimate_guillotine.history.repository import HistoryRepository, HistoryRowRejected

LOADED_AT = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def idle_conn():
    """A connection with no transaction open -- what a loader that forgot to open one holds.

    Autocommit, so a write that slipped past the guard would be published for real
    rather than quietly rolled back with the test.
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    with psycopg.connect(url, autocommit=True) as connection:
        yield connection


def _row(**overrides) -> CatalogRow:
    base = {
        "catalog_id": "2025-014",
        "season": 2025,
        "season_id": None,
        "week": 4,
        "occurred_on": None,
        "trade_type": "rental",
        "structure": "player-for-faab",
        "party_member_ids": [],
        "party_count": 2,
        "assets": [{"kind": "faab", "amount": 12, "from_party": 0, "to_party": 1}],
        "faab_total": 12,
        "confidence": "high",
        # Synthetic, and multi-paragraph on purpose: the column has to survive the newlines
        # the loader puts between two messages, and `to_jsonb` below compares it byte for byte.
        "announcement": "ANNOUNCEMENT-ONE\n\nANNOUNCEMENT-TWO",
        "unresolved_parties": 2,
        "loaded_at": LOADED_AT,
    }
    base.update(overrides)
    return CatalogRow(**base)


def _season_row(**overrides) -> SeasonResultRow:
    base = {
        "season": 2099,
        "season_id": None,
        "champion_member_id": None,
        "co_champion_member_id": None,
        "runner_up_member_id": None,
        "third_member_id": None,
        "team_count": 19,
        "eliminations": [
            {
                "week": 2,
                "order": 1,
                "member_id": None,
                "gulag_out": 2,
                "pool_out": 0,
                "remaining": None,
                "note": None,
            }
        ],
        "notes": None,
        "unresolved_names": 1,
        "loaded_at": LOADED_AT,
    }
    base.update(overrides)
    return SeasonResultRow(**base)


def test_catalog_upsert_inserts_then_updates(conn) -> None:
    repo = HistoryRepository(conn)

    assert repo.upsert_catalog(_row()) == "inserted"
    # The rerun after Ben corrects the catalog: a different amount, a lower confidence,
    # and an assets array that is a different shape, all onto the one row.
    corrected_assets = [
        {"kind": "faab", "amount": 15, "from_party": 0, "to_party": 1},
        {"kind": "condition", "label": "rental", "week": 9},
    ]
    assert (
        repo.upsert_catalog(_row(faab_total=15, confidence="medium", assets=corrected_assets))
        == "updated"
    )

    with conn.cursor() as cur:
        cur.execute(
            "select count(*), max(faab_total), max(confidence) from public.trade_catalog"
            " where catalog_id = %s",
            ("2025-014",),
        )
        assert cur.fetchone() == (1, 15, "medium")
        cur.execute(
            "select assets from public.trade_catalog where catalog_id = %s",
            ("2025-014",),
        )
        assert cur.fetchone()[0] == corrected_assets


def test_a_rerun_clears_an_announcement_the_file_no_longer_carries(conn) -> None:
    """The file is the source of truth for this column, so the upsert overwrites it.

    `season_results.notes` coalesces instead, because Ben types those on the command line
    and a rerun passes none -- here a run that passes none means the record lost its text,
    and a card that kept quoting text the file no longer holds would be quoting nothing.
    """
    repo = HistoryRepository(conn)
    assert repo.upsert_catalog(_row(catalog_id="2099-015")) == "inserted"
    assert repo.upsert_catalog(_row(catalog_id="2099-015", announcement=None)) == "updated"

    with conn.cursor() as cur:
        cur.execute(
            "select announcement from public.trade_catalog where catalog_id = %s", ("2099-015",)
        )
        assert cur.fetchone()[0] is None


def test_catalog_rerun_is_byte_identical(conn) -> None:
    """The idempotency claim, checked as a whole-row comparison rather than a count."""
    repo = HistoryRepository(conn)
    read_back = (
        "select to_jsonb(t) - 'id' - 'created_at' from public.trade_catalog t"
        " where catalog_id = %s"
    )
    repo.upsert_catalog(_row(catalog_id="2099-014"))
    with conn.cursor() as cur:
        cur.execute(read_back, ("2099-014",))
        first = cur.fetchone()[0]
    assert first["announcement"] == "ANNOUNCEMENT-ONE\n\nANNOUNCEMENT-TWO"
    repo.upsert_catalog(_row(catalog_id="2099-014"))
    with conn.cursor() as cur:
        cur.execute(read_back, ("2099-014",))
        assert cur.fetchone()[0] == first


def test_season_result_upsert_and_season_id_lookup(conn) -> None:
    """Season 2098 is nobody's real season on purpose.

    A real year would pass here until the day `ug history load-results` was run against
    this stack, and then fail as "updated" -- a test that goes red because the loader
    worked is a test about the machine, not about the upsert.
    """
    repo = HistoryRepository(conn)
    season_id = repo.season_id_for(2026)
    assert season_id is not None, "supabase seed inserts the 2026 season row"
    assert repo.season_id_for(1999) is None

    row = _season_row(season=2098)
    assert repo.upsert_season_result(row) == "inserted"

    with conn.cursor() as cur:
        cur.execute("select team_count, eliminations from public.season_results where season = 2098")
        team_count, eliminations = cur.fetchone()
    assert team_count == 19
    assert eliminations[0]["gulag_out"] == 2

    # The rerun after Ben fixes the workbook: a corrected count and a second week both
    # land on the one row rather than allocating another.
    second_week = {
        "week": 3,
        "order": 2,
        "member_id": None,
        "gulag_out": 1,
        "pool_out": 1,
        "remaining": 16,
        "note": None,
    }
    corrected = _season_row(
        season=2098, team_count=18, eliminations=[*row.eliminations, second_week]
    )
    assert repo.upsert_season_result(corrected) == "updated"

    with conn.cursor() as cur:
        cur.execute("select team_count, eliminations from public.season_results where season = 2098")
        rows = cur.fetchall()
    assert len(rows) == 1
    team_count, eliminations = rows[0]
    assert team_count == 18
    assert [entry["week"] for entry in eliminations] == [2, 3]


def test_season_result_rerun_is_byte_identical(conn) -> None:
    """The sentinel season 2099 is nobody's real season, so a rerun changing nothing is visible."""
    repo = HistoryRepository(conn)
    repo.upsert_season_result(_season_row())
    with conn.cursor() as cur:
        cur.execute(
            "select to_jsonb(t) - 'id' - 'created_at' from public.season_results t"
            " where season = 2099"
        )
        first = cur.fetchone()[0]
    repo.upsert_season_result(_season_row())
    with conn.cursor() as cur:
        cur.execute(
            "select to_jsonb(t) - 'id' - 'created_at' from public.season_results t"
            " where season = 2099"
        )
        assert cur.fetchone()[0] == first


def test_season_result_keeps_a_note_a_later_run_omits(conn) -> None:
    repo = HistoryRepository(conn)
    repo.upsert_season_result(_season_row(notes="two co-champions"))
    repo.upsert_season_result(_season_row(notes=None))
    with conn.cursor() as cur:
        cur.execute("select notes from public.season_results where season = 2099")
        assert cur.fetchone()[0] == "two co-champions"


def test_catalog_validator_rejection_names_the_id_not_the_text(conn) -> None:
    """A shape the database refuses is reported by catalog id; the offending text stays out."""
    repo = HistoryRepository(conn)
    bad = _row(
        catalog_id="2099-001",
        assets=[{"kind": "condition", "label": "he owed me one from the draft"}],
    )

    with pytest.raises(HistoryRowRejected) as excinfo:
        repo.upsert_catalog(bad)

    message = str(excinfo.value)
    assert "2099-001" in message
    assert "trade_catalog_assets_shape" in message
    assert "owed me one" not in message

    # The savepoint rolled back, so the connection is still usable for the next row.
    assert repo.upsert_catalog(_row()) == "inserted"


def test_season_result_validator_rejection_names_the_season(conn) -> None:
    repo = HistoryRepository(conn)
    bad = _season_row(eliminations=[{"week": 2, "gossip": "he tanked on purpose"}])

    with pytest.raises(HistoryRowRejected) as excinfo:
        repo.upsert_season_result(bad)

    message = str(excinfo.value)
    assert "2099" in message
    assert "season_results_eliminations_shape" in message
    assert "tanked" not in message

    assert repo.upsert_season_result(_season_row()) == "inserted"


def test_writes_require_the_callers_transaction(idle_conn) -> None:
    """A loader that forgot to open a transaction is refused, not quietly committed for."""
    repo = HistoryRepository(idle_conn)

    with pytest.raises(RuntimeError, match="require the caller's transaction"):
        repo.upsert_catalog(_row(catalog_id="2099-003"))
    with pytest.raises(RuntimeError, match="require the caller's transaction"):
        repo.upsert_season_result(_season_row())

    # The guard runs before the statement, so nothing reached the table -- on an
    # autocommit connection, anything that had would still be there.
    with idle_conn.cursor() as cur:
        cur.execute(
            "select count(*) from public.trade_catalog where catalog_id = %s", ("2099-003",)
        )
        assert cur.fetchone()[0] == 0
        cur.execute("select count(*) from public.season_results where season = 2099")
        assert cur.fetchone()[0] == 0

    # Reads need no transaction of their own; only writes are guarded.
    assert repo.season_id_for(1999) is None


def test_catalog_value_postgres_cannot_store_is_rejected_by_id(conn) -> None:
    """A faab total wider than int4 is a DataError, not a constraint violation -- same handling."""
    repo = HistoryRepository(conn)

    with pytest.raises(HistoryRowRejected) as excinfo:
        repo.upsert_catalog(_row(catalog_id="2099-002", faab_total=10**12))

    assert "2099-002" in str(excinfo.value)
    # The savepoint rolled back, so the connection is still usable for the next row.
    assert repo.upsert_catalog(_row()) == "inserted"


def test_catalog_source_defaults_to_catalog_and_a_rerun_can_change_it(conn) -> None:
    """Task 3 needs a trade registered through the league's own flow to say so."""
    repo = HistoryRepository(conn)
    assert repo.upsert_catalog(_row()) == "inserted"
    with conn.cursor() as cur:
        cur.execute("select source from public.trade_catalog where catalog_id = %s", ("2025-014",))
        assert cur.fetchone()[0] == "catalog"

    assert repo.upsert_catalog(_row(source="registered")) == "updated"
    with conn.cursor() as cur:
        cur.execute("select source from public.trade_catalog where catalog_id = %s", ("2025-014",))
        assert cur.fetchone()[0] == "registered"


def test_catalog_source_outside_the_migrations_two_values_is_refused(conn) -> None:
    repo = HistoryRepository(conn)

    with pytest.raises(HistoryRowRejected) as excinfo:
        repo.upsert_catalog(_row(catalog_id="2099-004", source="whatever-the-loader-liked"))

    message = str(excinfo.value)
    assert "2099-004" in message
    assert "whatever-the-loader-liked" not in message
