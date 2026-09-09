"""The reader's whole job is to drop things: private fields, unresolvable names, prose.

Every test here is a thing the classification file carries and the public table must
not: the analyst's notes, the chat lines a ruling was read out of, a nickname that two
members answer to, and the free-text return conditions that are most of the file.
"""

from datetime import UTC, date, datetime

import pytest

from ultimate_guillotine.history.catalog import (
    CATALOG_FIELDS,
    CONDITION_LABELS,
    CONDITION_PHRASES,
    MAX_NAME_LENGTH,
    CatalogRecordRefused,
    PlayerIndex,
    build_label_index,
    read_record,
    resolve_parties,
)
from ultimate_guillotine.history.repository import HistoryRepository
from ultimate_guillotine.sleeper.players import Player
from ultimate_guillotine.trades.models import MemberRef

LOADED_AT = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)

#: Two members answer to "Alpha"; only "Bravo" is anybody's alone.
MEMBERS = [
    MemberRef(1, "owner-one", ("Alpha", "The Alpha"), "Alpha", "Owner One"),
    MemberRef(2, "owner-two", ("Bravo",), "Bravo", "Bravo On Sleeper"),
    MemberRef(3, "owner-three", ("Alpha",), "Alpha", None),
]
NO_PLAYERS = PlayerIndex([])


def _record(**overrides) -> dict:
    """A record in the shape the analyst's file actually uses."""
    base = {
        "id": "2025-014",
        "season": 2025,
        "week_or_date": {"week": 4, "date": "2025-09-30"},
        "type": "rental_flat",
        "structure": "flat_fee_rental",
        "parties": ["Bravo", "Nobody"],
        "assets": {"players": [], "positions": [], "faab": [], "return_conditions": []},
        "faab_total": 12,
        "confidence": "high",
        "source": "chat",
        "notes": "SENTINEL-NOTE",
        "source_texts": ["SENTINEL-TEXT"],
    }
    base.update(overrides)
    return base


def test_private_fields_are_not_in_the_allowlist() -> None:
    assert "notes" not in CATALOG_FIELDS
    assert "source_texts" not in CATALOG_FIELDS


def test_row_carries_no_private_field() -> None:
    index = build_label_index([MEMBERS[1]])
    reading = read_record(_record(), index, NO_PLAYERS, season_id=None, loaded_at=LOADED_AT)

    assert "SENTINEL" not in repr(reading)
    assert reading.row.week == 4
    assert reading.row.occurred_on == date(2025, 9, 30)
    assert reading.row.party_member_ids == [2]
    assert reading.row.party_count == 2
    assert reading.row.unresolved_parties == 1
    assert reading.row.source == "catalog"


def test_week_or_date_is_a_dict_of_both() -> None:
    """The analyst dates every record and weeks most of them; a non-numeric week is dropped."""
    reading = read_record(
        _record(id="2023-002", week_or_date={"week": "Pre-Draft", "date": "2023-08-14"}),
        {}, NO_PLAYERS, season_id=None, loaded_at=LOADED_AT,
    )
    assert reading.row.week is None
    assert reading.row.occurred_on == date(2023, 8, 14)


def test_a_record_placed_in_neither_week_nor_date_keeps_both_columns_null() -> None:
    reading = read_record(
        _record(week_or_date={"week": None, "date": None}),
        {}, NO_PLAYERS, season_id=None, loaded_at=LOADED_AT,
    )
    assert reading.row.week is None and reading.row.occurred_on is None


def test_ambiguous_nickname_is_unresolved_rather_than_guessed() -> None:
    """Two members answer to "Alpha", so the catalog records a count, never a coin flip."""
    index = build_label_index(MEMBERS)
    ids, unresolved = resolve_parties(["Alpha", "Bravo"], index)
    assert ids == [2]
    assert unresolved == 1


def test_every_label_a_member_answers_to_resolves() -> None:
    """display_name, sleeper_display_name, nickname and the private aliases all match."""
    index = build_label_index([MEMBERS[1]])
    for label in ("owner-two", "Bravo On Sleeper", "bravo", "BRAVO"):
        assert resolve_parties([label], index) == ([2], 0)


def test_parallel_asset_lists_become_kind_objects() -> None:
    """The file keeps assets as parallel lists; the table keeps them as closed shapes."""
    reading = read_record(
        _record(assets={
            "players": ["Rookie One", "Nobody At All"],
            "positions": ["RB", "not-a-position"],
            "faab": [12, 0],
            "return_conditions": ["1 week", "gulag protections"],
        }),
        {},
        PlayerIndex([Player("4034", "Rookie One", "RB", "KC", True)]),
        season_id=None,
        loaded_at=LOADED_AT,
    )
    assert reading.row.assets == [
        {"kind": "player", "sleeper_player_id": "4034", "name": "Rookie One", "position": "RB"},
        {"kind": "player", "sleeper_player_id": None, "name": "Nobody At All", "position": None},
        {"kind": "faab", "amount": 12},
        {"kind": "condition", "label": "rental"},
        {"kind": "condition", "label": "conditional"},
    ]
    assert reading.unmapped_conditions == 0


def test_free_text_conditions_are_dropped_and_counted() -> None:
    """A sentence out of the chat is the one thing that could reach a public page."""
    reading = read_record(
        _record(assets={
            "players": [], "positions": [], "faab": [],
            "return_conditions": ["1 week", "SENTINEL is owed $40 back on survival"],
        }),
        {}, NO_PLAYERS, season_id=None, loaded_at=LOADED_AT,
    )
    assert reading.row.assets == [{"kind": "condition", "label": "rental"}]
    assert reading.unmapped_conditions == 1
    assert "SENTINEL" not in repr(reading)


def test_one_label_per_record_however_many_phrases_said_it() -> None:
    reading = read_record(
        _record(assets={
            "players": [], "positions": [], "faab": [],
            "return_conditions": ["1 week", "one week hold", "hold"],
        }),
        {}, NO_PLAYERS, season_id=None, loaded_at=LOADED_AT,
    )
    assert reading.row.assets == [{"kind": "condition", "label": "rental"}]


def test_every_mapped_phrase_lands_on_a_label_the_database_accepts() -> None:
    assert set(CONDITION_PHRASES.values()) <= CONDITION_LABELS


def test_a_confidence_the_analyst_invented_is_read_as_low() -> None:
    reading = read_record(
        _record(confidence="pretty sure"), {}, NO_PLAYERS, season_id=None, loaded_at=LOADED_AT
    )
    assert reading.row.confidence == "low"


def test_a_player_name_two_players_answer_to_keeps_the_name_and_no_id() -> None:
    players = PlayerIndex([
        Player("1", "Rookie One", "RB", "KC", True),
        Player("2", "Rookie One", "WR", "SF", True),
    ])
    reading = read_record(
        _record(assets={
            "players": ["Rookie One"], "positions": ["RB"], "faab": [], "return_conditions": [],
        }),
        {}, players, season_id=None, loaded_at=LOADED_AT,
    )
    assert reading.row.assets == [
        {"kind": "player", "sleeper_player_id": None, "name": "Rookie One", "position": "RB"}
    ]


def test_a_bare_surname_never_becomes_a_player_id() -> None:
    """One "One" on today's roster is not evidence about a trade made three seasons ago.

    The registrar may match a surname -- it is reading a live message about two rosters
    it can see. The catalog reads five seasons of chat against today's active players,
    so a single token keeps the name and no id rather than credit the wrong man.
    """
    players = PlayerIndex([Player("4034", "Rookie One", "RB", "KC", True)])
    assert players.id_for("One") is None

    reading = read_record(
        _record(assets={
            "players": ["One"], "positions": ["RB"], "faab": [], "return_conditions": [],
        }),
        {}, players, season_id=None, loaded_at=LOADED_AT,
    )
    assert reading.row.assets == [
        {"kind": "player", "sleeper_player_id": None, "name": "One", "position": "RB"}
    ]


def test_a_team_defense_still_resolves() -> None:
    """The one spelling that is not a full name and still means exactly one player."""
    players = PlayerIndex([Player("KC", "Kansas City Chiefs", "DEF", "KC", True)])
    assert players.id_for("KC defense") == "KC"


def test_a_players_entry_that_is_not_a_string_is_not_a_name() -> None:
    """A number or an object in the names list is unreadable, not a name to stringify."""
    reading = read_record(
        _record(assets={
            "players": [12, None, {"name": "SENTINEL"}, "Rookie One"],
            "positions": ["RB", "RB", "RB", "WR"],
            "faab": [], "return_conditions": [],
        }),
        {}, NO_PLAYERS, season_id=None, loaded_at=LOADED_AT,
    )
    assert reading.row.assets == [
        {"kind": "player", "sleeper_player_id": None, "name": "Rookie One", "position": "WR"}
    ]
    assert "SENTINEL" not in repr(reading)


@pytest.mark.parametrize("field", ["type", "structure"])
def test_a_type_or_structure_longer_than_a_label_refuses_the_record(field: str) -> None:
    """Past the cap the field is holding a sentence, and the column would take it."""
    with pytest.raises(CatalogRecordRefused) as refusal:
        read_record(
            _record(**{field: "SENTINEL " * 20}), {}, NO_PLAYERS,
            season_id=None, loaded_at=LOADED_AT,
        )
    assert "2025-014" in str(refusal.value)
    assert "SENTINEL" not in str(refusal.value)


@pytest.mark.parametrize("field", ["type", "structure"])
def test_a_type_or_structure_at_the_cap_is_published(field: str) -> None:
    reading = read_record(
        _record(**{field: "x" * MAX_NAME_LENGTH}), {}, NO_PLAYERS,
        season_id=None, loaded_at=LOADED_AT,
    )
    assert getattr(reading.row, "trade_type" if field == "type" else field) == "x" * MAX_NAME_LENGTH


def test_a_player_name_longer_than_a_name_is_dropped_whole() -> None:
    reading = read_record(
        _record(assets={
            "players": ["SENTINEL " * 20], "positions": ["RB"], "faab": [], "return_conditions": [],
        }),
        {}, NO_PLAYERS, season_id=None, loaded_at=LOADED_AT,
    )
    assert reading.row.assets == []
    assert "SENTINEL" not in repr(reading)


@pytest.mark.parametrize("faab", [[0], [-5], ["12"], [True]])
def test_faab_that_is_not_a_positive_whole_number_is_not_an_asset(faab: list) -> None:
    reading = read_record(
        _record(assets={
            "players": [], "positions": [], "faab": faab, "return_conditions": [],
        }),
        {}, NO_PLAYERS, season_id=None, loaded_at=LOADED_AT,
    )
    assert reading.row.assets == []


def test_the_row_the_reader_builds_is_one_the_database_accepts(conn) -> None:
    """The jsonb validators are the same allowlist restated; this proves they agree."""
    reading = read_record(
        _record(assets={
            "players": ["Rookie One"],
            "positions": ["RB"],
            "faab": [12],
            "return_conditions": ["1 week", "all permanent", "no gulag protections"],
        }),
        {}, NO_PLAYERS, season_id=None, loaded_at=LOADED_AT,
    )
    assert HistoryRepository(conn).upsert_catalog(reading.row) == "inserted"
    assert reading.unmapped_conditions == 1
