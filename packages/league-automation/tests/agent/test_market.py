from pathlib import Path
from unittest.mock import MagicMock, Mock

import httpx

from ultimate_guillotine.agent.tools.league import market_history
from ultimate_guillotine.agent.tools.market import bid_summary, market_records
from ultimate_guillotine.agent.tools.source import DatabaseSource, FixtureSource


class MarketSource(FixtureSource):
    def historical_transactions(self, season, week=None):
        if season != 2025:
            return {"error": "No archived league"}
        def tx(key, status, amount, notes=None):
            return {"transaction_id": key, "type": "waiver", "leg": 6,
                    "status": status, "settings": {"waiver_bid": amount},
                    "metadata": {"notes": notes}, "created": 1,
                    "adds": {"p05s0": 5}, "drops": None}
        winner = tx("winner", "complete", 40)
        return {"raw": [winner, winner, tx("loser", "failed", 35, "Outbid"),
                        tx("invalid", "failed", 100, "Roster full"),
                        tx("pending", "pending", 999)],
                "labels": {5: "Member05"}, "names": {"p05s0": "Starter 05-0"},
                "weeks_requested": list(range(19)), "fetched_at": "2026-10-08T16:00:00Z"}


def test_settled_bids_keep_failure_reasons_and_do_not_expose_pending_claims():
    rows, coverage = market_records(MarketSource(), [2024, 2025])
    assert len(rows) == 3
    assert {r["id"] for r in rows} == {"winner", "loser", "invalid"}
    assert coverage[0]["platform_available"] is False
    assert coverage[1]["weeks_requested"] == list(range(19))
    summary = bid_summary(rows)
    assert summary["winning_bid_median"] == 40
    assert summary["failed_bid_count"] == 2
    assert summary["failure_reasons"] == {"Outbid": 1, "Roster full": 1}


def test_market_search_paginates_and_carries_current_state_and_gaps():
    result = market_history(MarketSource(), player="Starter 05-0", member="Member05", limit=1)
    assert result["platform_total_matches"] == 3
    assert result["next_offset"] == 1
    assert len(result["platform_records"]) == 1
    assert result["current_market"]["active_teams"] == 17
    assert len(result["coverage"]) == 3
    last = market_history(MarketSource(), offset=2, limit=1)
    assert last["next_offset"] is None
    assert "error" in market_history(MarketSource(), limit=0)


def test_one_unavailable_api_season_does_not_hide_other_evidence():
    class Unavailable(MarketSource):
        def historical_transactions(self, season, week=None):
            if season == 2024:
                raise httpx.ReadTimeout("credentials should never be printed")
            return super().historical_transactions(season, week)
    rows, coverage = market_records(Unavailable(), [2024, 2025])
    assert len(rows) == 3
    assert coverage[0]["error"] == "ReadTimeout"


def test_position_filter_does_not_mix_unrelated_prices():
    result = market_history(MarketSource(), position="RB")
    assert result["platform_total_matches"] == 0
    assert result["bids"]["winning_bid_median"] is None


def test_complete_history_cache_retains_failed_bids_and_includes_preseason(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    def prepare(sql, params):
        if "select distinct sleeper_league_id" in sql:
            cur.fetchall.return_value = [("fixture-league",)]
        elif "manager_label" in sql or "sleeper_roster_id" in sql:
            cur.fetchall.return_value = [(5, "Member05")]
        else:
            cur.fetchall.return_value = [("p05s0", "Starter 05-0")]
    cur.execute.side_effect = prepare
    sleeper = Mock()
    sleeper.get_users.return_value = []
    sleeper.get_rosters.return_value = []
    sleeper.get_transactions.side_effect = lambda league, week: [
        {"transaction_id": str(week), "status": "failed", "type": "waiver",
         "leg": week, "adds": {"p05s0": 5}, "settings": {"waiver_bid": 9}}]
    source = DatabaseSource(conn, sleeper, "fixture-league")
    first = source.historical_transactions(2025)
    second = source.historical_transactions(2025)
    assert first["raw"] == second["raw"]
    assert len(first["raw"]) == 19
    assert first["weeks_requested"] == list(range(19))
    assert sleeper.get_transactions.call_count == 19
    assert all(row["status"] == "failed" for row in second["raw"])
