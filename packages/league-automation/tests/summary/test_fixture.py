"""The fixture league the summary is rehearsed against: every case, in one snapshot."""

from ultimate_guillotine.summary.fixture import FIXTURE_NOW, fixture_eod
from ultimate_guillotine.summary.survival import simulate


def test_the_fixture_is_the_agent_s_league_on_a_sunday_night() -> None:
    snap = fixture_eod()
    assert len(snap.teams) == 18
    assert snap.week == 6
    assert snap.day_state == "midweek"
    assert (snap.games_final, snap.games_total) == (13, 16)
    assert snap.schedule_available
    assert snap.team(117).is_eliminated


def test_the_fixture_has_every_kind_of_starter_and_a_pairing_to_show() -> None:
    snap = fixture_eod()
    statuses = {s.status for t in snap.teams for s in t.starters}
    assert {"done", "remaining", "out", "empty"} <= statuses
    assert snap.phase.kind == "gulag"
    assert snap.phase.gulag_source == "replay"
    assert len(snap.phase.gulag_team_ids) == 2
    assert any(t.empty_slots() for t in snap.live_teams())
    assert any(t.unprojected_pending() for t in snap.live_teams())
    assert snap.moves


def test_the_fixture_simulates_to_a_mix_of_odds() -> None:
    result = simulate(fixture_eod(), simulations=300)
    odds = [o.probability for o in result.teams.values()]
    assert len(result.teams) == 17
    assert min(odds) < max(odds)
    assert any(o.is_estimated for o in result.teams.values())


def test_the_fixture_can_be_asked_for_the_other_days() -> None:
    assert fixture_eod(day_state="outlook").day_state == "outlook"
    assert fixture_eod(day_state="final").day_state == "final"
    dark = fixture_eod(schedule_available=False)
    assert not dark.schedule_available
    assert dark.day_state == "unknown"
    assert FIXTURE_NOW.tzinfo is not None
