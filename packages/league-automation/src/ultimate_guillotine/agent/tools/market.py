"""Search settled market evidence without confusing failed claims with acquisitions."""

from collections import Counter
from statistics import median

import httpx
import psycopg


def market_records(source, seasons):
    records = []
    coverage = []
    for season in seasons:
        try:
            payload = source.historical_transactions(season)
        except (httpx.HTTPError, psycopg.Error, OSError, ValueError) as exc:
            coverage.append(
                {"season": season, "platform_available": False, "error": type(exc).__name__}
            )
            continue
        if "error" in payload:
            coverage.append(
                {"season": season, "platform_available": False, "error": payload["error"]}
            )
            continue
        coverage.append(
            {
                "season": season,
                "platform_available": True,
                "fetched_at": payload.get("fetched_at"),
                "weeks_requested": payload.get("weeks_requested"),
                "records_returned": len(payload["raw"]),
            }
        )
        names, labels = payload["names"], payload["labels"]
        seen = set()
        for raw in payload["raw"]:
            key = raw.get("transaction_id")
            if key in seen:
                continue
            seen.add(key)
            # Unprocessed bids are sealed, and are not evidence of willingness to pay.
            if raw.get("status") not in ("complete", "failed"):
                continue
            moves = []
            for field in ("adds", "drops"):
                for player_id, roster_id in (raw.get(field) or {}).items():
                    moves.append(
                        {
                            "action": field,
                            "player_id": str(player_id),
                            "player": names.get(player_id) or str(player_id),
                            "member": labels.get(roster_id, f"roster {roster_id}"),
                        }
                    )
            records.append(
                {
                    "source": "Sleeper",
                    "season": season,
                    "id": key,
                    "week": raw.get("leg"),
                    "type": raw.get("type"),
                    "status": raw.get("status"),
                    "moves": moves,
                    "waiver_bid": (raw.get("settings") or {}).get("waiver_bid"),
                    "failure_reason": (raw.get("metadata") or {}).get("notes"),
                    "created": raw.get("created"),
                    "faab_transfers": [
                        {
                            "amount": leg.get("amount"),
                            "from": labels.get(leg.get("sender"), "unknown"),
                            "to": labels.get(leg.get("receiver"), "unknown"),
                        }
                        for leg in raw.get("waiver_budget") or []
                    ],
                }
            )
    return records, coverage


def select_records(records, query=None, member=None, position=None, players=None):
    selected = []
    for row in records:
        moves = row["moves"]
        if query and not any(
            query.casefold() in m["player"].casefold() or query == m["player_id"] for m in moves
        ):
            continue
        if member and not any(m["member"].casefold() == member.casefold() for m in moves):
            continue
        if position and not any(
            m["player_id"] in (players or {})
            and players[m["player_id"]].position == position.upper()
            for m in moves
        ):
            continue
        selected.append(row)
    return selected


def bid_summary(records):
    bids = [
        r
        for r in records
        if r["type"] == "waiver"
        and isinstance(r["waiver_bid"], int)
        and not isinstance(r["waiver_bid"], bool)
    ]
    won = [r["waiver_bid"] for r in bids if r["status"] == "complete"]
    failed = [r["waiver_bid"] for r in bids if r["status"] == "failed"]
    return {
        "winning_bid_count": len(won),
        "failed_bid_count": len(failed),
        "winning_bid_median": median(won) if won else None,
        "failed_bid_median": median(failed) if failed else None,
        "failure_reasons": dict(
            Counter(r["failure_reason"] or "not supplied" for r in bids if r["status"] == "failed")
        ),
        "interpretation": "Failed claims are not necessarily outbid. Roster limits, "
        "priority and invalid claims can also cause failure. "
        "Historical bids are observations, not a recommended price.",
    }
