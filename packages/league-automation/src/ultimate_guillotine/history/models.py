"""The only two shapes that reach the public history tables.

Deliberately id-only: no member name, nickname, or workbook cell has a field to
live in, so nothing private can be carried into Postgres by accident. `announcement`
is the single exception and it is a narrow one -- the league's own announcement of a
trade, published on Ben's ruling of 2026-09-10 because the cards were unreadable
without it. It is the trade's text, not the analyst's: `notes` still has nowhere here
to live.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class CatalogRow:
    catalog_id: str
    season: int
    season_id: int | None
    week: int | None
    occurred_on: date | None
    trade_type: str
    structure: str
    party_member_ids: list[int]
    party_count: int
    assets: list[dict[str, Any]]
    faab_total: int | None
    confidence: str
    unresolved_parties: int
    loaded_at: datetime
    # Where the trade came from: the analyst's catalog, or a trade registered through
    # the league's own flow. The migration's check constraint holds the same two
    # values, so a third one is refused by the database rather than published.
    source: str = "catalog"
    # What the league said when the trade was made, or None for a record that carried
    # no text. Defaulted so every caller that predates the column still builds a row --
    # a missing announcement is a card with no quote, not a broken load.
    announcement: str | None = None


@dataclass(frozen=True)
class SeasonResultRow:
    season: int
    season_id: int | None
    champion_member_id: int | None
    co_champion_member_id: int | None
    runner_up_member_id: int | None
    third_member_id: int | None
    team_count: int | None
    eliminations: list[dict[str, Any]] = field(default_factory=list)
    notes: str | None = None
    unresolved_names: int = 0
    loaded_at: datetime | None = None
