"""What the league has actually paid, read off the trades it registered.

The Advisor's whole claim to being defensible is that it quotes prices the
league set itself rather than a ranking from somewhere on the internet. Those
prices live in ``public.trade_revisions.terms``, which is a dumped
``TradeProposal``: a list of assets with a kind, a direction, a player id, and
an amount. This module turns each accepted trade into one price point per
player who moved.

FAAB is the only currency a proposal may use, so only FAAB price points become
comparables. A trade paid in dollars or draft dollars is still recorded -- it
is a real thing the league did -- but it never prices a suggestion, and a
payment that mixed dollars in alongside FAAB is quoted on its FAAB leg alone so
the currency the Advisor may actually propose is never inflated by one it
may not. Such a payment is recorded *unit-only*: the ``unit`` survives on the
price point but the amount does not, because :attr:`PricePoint.faab` is the
only field a number can live in and putting dollars there would make them
quotable. The history therefore says the league once paid in dollars without
saying how many; a reader who needs the figure reads the trade.

Only permanent acquisitions price a suggestion. Rentals and payments are
aggregated the same way and kept, but :func:`comparables_for` and
:func:`median_faab` leave them out unless a caller names them, because a
rental's FAAB buys a few weeks of a player rather than the player.

A price point carries ids and never labels. The terms document has a
``display_name`` on every party, but a comparable is shown to whoever asked and
describes a trade between two other people; resolving those ids to names is the
caller's decision, made once, where the audience is known. Nothing here is
keyed on a particular member either: :func:`comparables_for` and
:func:`median_faab` answer questions about a *position*, so the same history
prices the same position identically for all eighteen teams.

A season the league never traded in is not an error. It yields no price points,
the comparables come back empty, and the median comes back ``None`` -- which is
what lets the Advisor say it has no precedent instead of inventing one.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import median

import psycopg

#: Ceiling on how much history one run reads. Two seasons of an 18-team league
#: is well under this; the cap exists so a backfilled decade cannot bloat a run.
DEFAULT_LIMIT = 200

#: Asset kinds that carry an amount. Only ``faab`` ever prices a suggestion;
#: the other two are recorded so the history reads honestly.
CURRENCY_KINDS = ("faab", "usd", "draft_dollars")

#: The trade kinds a comparable may be drawn from. A rental is a loan and a
#: payment settles an earlier deal; neither is what a permanent acquisition
#: costs, so neither prices one unless a caller asks for it by name.
COMPARABLE_KINDS: tuple[str, ...] = ("permanent",)


@dataclass(frozen=True)
class PricePoint:
    """One player's move in one trade, and whatever went back the other way."""

    trade_code: str
    season: int
    kind: str
    position: str | None
    player_name: str | None
    player_id: str | None
    faab: int | None
    unit: str | None
    players_back: int
    effective_week: int | None
    from_member_id: int | None
    to_member_id: int | None


def _money_assets(assets: Sequence[dict]) -> list[dict]:
    return [a for a in assets if a.get("kind") in CURRENCY_KINDS]


def _unit_of(asset: dict) -> str | None:
    return asset.get("unit") or asset.get("kind")


def price_points(rows: Iterable[dict], positions: Mapping[str, str | None]) -> list[PricePoint]:
    """One price point per player who changed hands in each trade.

    The price of a player is whatever money went the other way, split evenly
    across the players that money bought -- two players for 100 FAAB is two
    50-FAAB players, which is the honest reading of a package deal. Players
    coming back the other way are counted rather than valued: ``players_back``
    is what tells a reader the FAAB was not the whole price.

    The split is :class:`~decimal.Decimal` arithmetic and lands on a whole
    number of FAAB, because FAAB is a whole number of dollars in this league and
    a float share of it would quote a price nobody could bid.

    Every trade kind is aggregated here, including rentals and payments; it is
    the reading functions that decide which kinds may be quoted. A player whose
    sender the extractor could not name is recorded with no price at all.
    """
    points: list[PricePoint] = []
    for row in rows:
        terms = row.get("terms") or {}
        assets = terms.get("assets") or []
        players = [a for a in assets if a.get("kind") == "player"]
        money = _money_assets(assets)
        for asset in players:
            sender = asset.get("from_member_id")
            # An unnamed sender is nobody money can flow back to. Matching
            # ``None`` against every payment with an unstated recipient would
            # conjure a price out of two things the extractor failed to
            # attribute, so an unattributed move is recorded with no price.
            paid: list[dict] = (
                []
                if sender is None
                else [
                    m
                    for m in money
                    if m.get("to_member_id") == sender and m.get("amount") is not None
                ]
            )
            faab_paid = [m for m in paid if _unit_of(m) == "faab"]
            priced = faab_paid or paid
            bought = [p for p in players if p.get("from_member_id") == sender]
            back = len([p for p in players if p.get("to_member_id") == sender])
            unit = _unit_of(priced[0]) if priced else None
            total = sum((Decimal(int(m["amount"])) for m in priced), Decimal(0))
            share = int(total / len(bought)) if priced and bought else None
            player_id = asset.get("player_id")
            points.append(
                PricePoint(
                    trade_code=row["trade_code"],
                    season=int(row["season"]),
                    kind=str(terms.get("kind") or "permanent"),
                    position=positions.get(player_id) if player_id else None,
                    player_name=asset.get("player_name"),
                    player_id=player_id,
                    faab=share if unit == "faab" else None,
                    unit=unit,
                    players_back=back,
                    effective_week=terms.get("effective_week"),
                    from_member_id=sender,
                    to_member_id=asset.get("to_member_id"),
                )
            )
    return points


def comparables_for(
    points: Sequence[PricePoint],
    position: str,
    *,
    limit: int = 3,
    kinds: tuple[str, ...] = COMPARABLE_KINDS,
) -> list[PricePoint]:
    """FAAB-priced points at one position, newest season and biggest price first.

    Restricted to permanent acquisitions unless the caller says otherwise. A
    rental at 30 FAAB is a real price the league set, but it is the price of
    borrowing a player for a few weeks; quoting it beside a permanent
    acquisition would tell a manager that position goes for less than it does.
    A caller who wants those asks for them by name: ``kinds=("rental",)``.
    """
    matching = [
        p for p in points if p.position == position and p.faab is not None and p.kind in kinds
    ]
    matching.sort(key=lambda p: (-p.season, -(p.faab or 0), p.trade_code))
    return matching[:limit]


def median_faab(
    points: Sequence[PricePoint],
    position: str,
    *,
    kinds: tuple[str, ...] = COMPARABLE_KINDS,
) -> int | None:
    """The league's typical FAAB price at a position, or ``None`` with no history.

    Filtered by trade kind on the same terms as :func:`comparables_for`, so a
    median and the comparables shown beneath it always come from one population.
    """
    prices = [
        p.faab for p in points if p.position == position and p.faab is not None and p.kind in kinds
    ]
    return int(median(prices)) if prices else None


class PriceRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def accepted_terms(self, seasons: Sequence[int], limit: int = DEFAULT_LIMIT) -> list[dict]:
        """Current terms of every live trade in these seasons, newest first.

        Only the current revision of a trade counts: an amended trade was paid
        at the price it ended on, not the one it was first announced at.
        Rescinded trades are excluded, because a price the league took back is
        not a price the league paid, and so are ``TEST-`` codes, which are gate
        rehearsals rather than deals anybody agreed to.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select t.trade_code, s.year, r.terms
                from public.trades t
                join public.seasons s on s.id = t.season_id
                join public.trade_revisions r on r.id = t.current_revision_id
                where t.status = 'accepted'
                  and t.trade_code not like 'TEST-%%'
                  and s.year = any(%s)
                order by s.year desc, t.id desc
                limit %s
                """,
                (list(seasons), limit),
            )
            return [
                {"trade_code": row[0], "season": row[1], "terms": row[2]} for row in cur.fetchall()
            ]

    def positions_for(self, player_ids: Sequence[str]) -> dict[str, str | None]:
        """Positions for the Sleeper ids that appear in a run's history.

        Traded players leave rosters, so the snapshot cannot answer this for
        everyone the league has ever dealt: ``public.players`` can, and a player
        it has never heard of is simply absent, which reads as an unknown
        position rather than a wrong one.
        """
        ids = list(player_ids)
        if not ids:
            return {}
        with self._conn.cursor() as cur:
            cur.execute(
                "select sleeper_player_id, position from public.players"
                " where sleeper_player_id = any(%s)",
                (ids,),
            )
            return {row[0]: row[1] for row in cur.fetchall()}
