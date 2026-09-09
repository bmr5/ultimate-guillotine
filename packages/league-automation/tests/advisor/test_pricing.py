"""What the league has paid before, read off the trades it registered.

Every expected number here is small enough to check by hand: a 120-FAAB player
is one price point of 120, and 100 FAAB for two players is two price points of
50. The point of the table tests is that the *rules* are visible -- what counts
as a price, what counts as a swap, and what is recorded but never quoted --
without a database in the way. Only the repository test needs one.
"""

import json

from ultimate_guillotine.advisor.pricing import (
    PriceRepository,
    comparables_for,
    median_faab,
    price_points,
)

POSITIONS = {"pa": "RB", "pb": "WR", "pc": "RB"}

#: A season no sync will ever have written, so the repository test never collides
#: with -- or reads -- the real trades a developer's local stack already carries.
SENTINEL_SEASON = 2099


def _terms(assets: list[dict], week: int | None = 5, kind: str = "permanent") -> dict:
    return {
        "season": 2025, "effective_week": week, "kind": kind,
        "parties": [
            {"member_id": 1, "display_name": "Member01"},
            {"member_id": 2, "display_name": "Member02"},
        ],
        "assets": assets, "special_terms": [],
    }


def _asset(kind, from_id, to_id, player_id=None, player_name=None, amount=None, unit=None):
    return {
        "kind": kind, "from_member_id": from_id, "to_member_id": to_id,
        "player_id": player_id, "player_name": player_name, "amount": amount,
        "unit": unit, "description": None,
    }


def test_a_player_for_faab_becomes_one_price_point() -> None:
    rows = [{"trade_code": "T-2025-001", "season": 2025, "terms": _terms([
        _asset("player", 1, 2, "pa", "Alpha"),
        _asset("faab", 2, 1, amount=120, unit="faab"),
    ])}]
    points = price_points(rows, POSITIONS)
    assert len(points) == 1
    point = points[0]
    assert point.trade_code == "T-2025-001" and point.position == "RB"
    assert point.player_name == "Alpha" and point.faab == 120
    assert point.players_back == 0 and point.effective_week == 5


def test_faab_is_split_across_the_players_it_paid_for() -> None:
    rows = [{"trade_code": "T-2025-002", "season": 2025, "terms": _terms([
        _asset("player", 1, 2, "pa", "Alpha"),
        _asset("player", 1, 2, "pc", "Gamma"),
        _asset("faab", 2, 1, amount=100, unit="faab"),
    ])}]
    assert [p.faab for p in price_points(rows, POSITIONS)] == [50, 50]


def test_a_player_for_player_records_the_swap_not_a_price() -> None:
    rows = [{"trade_code": "T-2025-003", "season": 2025, "terms": _terms([
        _asset("player", 1, 2, "pa", "Alpha"),
        _asset("player", 2, 1, "pb", "Beta"),
    ])}]
    points = price_points(rows, POSITIONS)
    assert {p.player_name for p in points} == {"Alpha", "Beta"}
    assert all(p.faab is None and p.players_back == 1 for p in points)


def test_non_faab_currencies_keep_their_unit_and_never_price_a_proposal() -> None:
    rows = [{"trade_code": "T-2025-004", "season": 2025, "terms": _terms([
        _asset("player", 1, 2, "pa", "Alpha"),
        _asset("usd", 2, 1, amount=25, unit="usd"),
    ])}]
    point = price_points(rows, POSITIONS)[0]
    assert point.unit == "usd" and point.faab is None
    assert comparables_for([point], "RB") == []


def test_comparables_prefer_the_newest_season_and_the_biggest_price() -> None:
    rows = [
        {"trade_code": "T-2025-005", "season": 2025, "terms": _terms([
            _asset("player", 1, 2, "pa", "Alpha"),
            _asset("faab", 2, 1, amount=40, unit="faab"),
        ])},
        {"trade_code": "T-2026-001", "season": 2026, "terms": _terms([
            _asset("player", 1, 2, "pc", "Gamma"),
            _asset("faab", 2, 1, amount=90, unit="faab"),
        ])},
    ]
    points = price_points(rows, POSITIONS)
    assert [p.trade_code for p in comparables_for(points, "RB")] == [
        "T-2026-001", "T-2025-005",
    ]
    assert comparables_for(points, "TE") == []
    assert median_faab(points, "RB") == 65
    assert median_faab(points, "TE") is None


def test_a_price_point_carries_the_counterparties_as_ids_not_labels() -> None:
    """The terms carry display names; a price point deliberately does not.

    Labels belong to whoever renders the advice, and a price point that carried
    one would be a place for a member's name to leak into a shared comparable.
    """
    rows = [{"trade_code": "T-2025-006", "season": 2025, "terms": _terms([
        _asset("player", 1, 2, "pa", "Alpha"),
        _asset("faab", 2, 1, amount=30, unit="faab"),
    ])}]
    point = price_points(rows, POSITIONS)[0]
    assert (point.from_member_id, point.to_member_id) == (1, 2)
    assert "Member01" not in repr(point)


def test_a_mixed_currency_payment_is_priced_on_its_faab_leg_only() -> None:
    """Dollars alongside FAAB do not inflate the FAAB the league can quote."""
    rows = [{"trade_code": "T-2025-007", "season": 2025, "terms": _terms([
        _asset("player", 1, 2, "pa", "Alpha"),
        _asset("faab", 2, 1, amount=60, unit="faab"),
        _asset("usd", 2, 1, amount=25, unit="usd"),
    ])}]
    point = price_points(rows, POSITIONS)[0]
    assert point.unit == "faab" and point.faab == 60


def test_a_player_with_no_position_known_is_recorded_but_never_compared() -> None:
    rows = [{"trade_code": "T-2025-008", "season": 2025, "terms": _terms([
        _asset("player", 1, 2, "pz", "Zeta"),
        _asset("faab", 2, 1, amount=70, unit="faab"),
    ])}]
    points = price_points(rows, POSITIONS)
    assert points[0].position is None and points[0].player_id == "pz"
    assert comparables_for(points, "RB") == [] and median_faab(points, "RB") is None


def test_a_season_with_no_trades_has_no_prices_rather_than_an_error() -> None:
    assert price_points([], POSITIONS) == []
    assert comparables_for([], "RB") == []
    assert median_faab([], "RB") is None


def test_accepted_terms_reads_only_live_trades(conn) -> None:
    _seed_trades(conn)
    rows = PriceRepository(conn).accepted_terms([SENTINEL_SEASON])
    assert [row["trade_code"] for row in rows] == ["T-2099-001"]
    assert rows[0]["season"] == SENTINEL_SEASON
    assert rows[0]["terms"]["assets"][0]["player_id"] == "pa"
    assert PriceRepository(conn).accepted_terms([SENTINEL_SEASON - 1]) == []


def test_positions_for_reads_the_player_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.players (sleeper_player_id, full_name, position, synced_at)"
            " values ('sentinel-pa', 'Alpha', 'RB', now())"
            " on conflict (sleeper_player_id) do update set position = 'RB'"
        )
    positions = PriceRepository(conn).positions_for(["sentinel-pa", "sentinel-pz"])
    assert positions == {"sentinel-pa": "RB"}
    assert PriceRepository(conn).positions_for([]) == {}


def _seed_trades(conn) -> None:
    """One accepted trade, one rescinded trade, and one gate rehearsal."""
    with conn.cursor() as cur:
        cur.execute(
            "insert into public.seasons (year, sleeper_league_id, rules_version)"
            " values (%s, 'L1', 'v1') returning id",
            (SENTINEL_SEASON,),
        )
        season_id = cur.fetchone()[0]
        codes = (
            ("T-2099-001", "accepted"),
            ("T-2099-002", "rescinded"),
            ("TEST-2099-001", "accepted"),
        )
        for code, status in codes:
            cur.execute(
                "insert into public.trades (season_id, trade_code, status)"
                " values (%s, %s, %s) returning id",
                (season_id, code, status),
            )
            trade_id = cur.fetchone()[0]
            cur.execute(
                "insert into public.trade_revisions"
                " (trade_id, revision, terms, effective_week)"
                " values (%s, 1, %s, 5) returning id",
                (trade_id, json.dumps(_terms([
                    _asset("player", 1, 2, "pa", "Alpha"),
                    _asset("faab", 2, 1, amount=120, unit="faab"),
                ]))),
            )
            revision_id = cur.fetchone()[0]
            cur.execute(
                "update public.trades set current_revision_id = %s where id = %s",
                (revision_id, trade_id),
            )
