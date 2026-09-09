"""The two upserts, against the local stack. `conn` rolls back, so these leave nothing."""

from datetime import UTC, datetime

import pytest

from ultimate_guillotine.history.models import CatalogRow, SeasonResultRow
from ultimate_guillotine.history.repository import HistoryRepository, HistoryRowRejected

LOADED_AT = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


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
    assert repo.upsert_catalog(_row(faab_total=15, confidence="medium")) == "updated"

    with conn.cursor() as cur:
        cur.execute(
            "select count(*), max(faab_total), max(confidence) from public.trade_catalog"
            " where catalog_id = %s",
            ("2025-014",),
        )
        assert cur.fetchone() == (1, 15, "medium")


def test_catalog_rerun_is_byte_identical(conn) -> None:
    """The idempotency claim, checked as a whole-row comparison rather than a count."""
    repo = HistoryRepository(conn)
    repo.upsert_catalog(_row())
    with conn.cursor() as cur:
        cur.execute("select to_jsonb(t) - 'id' - 'created_at' from public.trade_catalog t")
        first = cur.fetchone()[0]
    repo.upsert_catalog(_row())
    with conn.cursor() as cur:
        cur.execute("select to_jsonb(t) - 'id' - 'created_at' from public.trade_catalog t")
        assert cur.fetchone()[0] == first


def test_season_result_upsert_and_season_id_lookup(conn) -> None:
    repo = HistoryRepository(conn)
    season_id = repo.season_id_for(2026)
    assert season_id is not None, "supabase seed inserts the 2026 season row"
    assert repo.season_id_for(1999) is None

    row = _season_row(season=2024)
    assert repo.upsert_season_result(row) == "inserted"
    assert repo.upsert_season_result(row) == "updated"

    with conn.cursor() as cur:
        cur.execute("select team_count, eliminations from public.season_results where season = 2024")
        team_count, eliminations = cur.fetchone()
    assert team_count == 19
    assert eliminations[0]["gulag_out"] == 2


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
