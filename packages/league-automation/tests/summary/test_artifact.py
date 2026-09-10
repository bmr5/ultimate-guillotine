"""The HTML artifact: the whole summary as one self-contained file for Quick Look.

Ben (2026-09-10): "what I would prefer here is an html that can be sent, similar
to a claude artifact pattern." The file is attached to the chat after a short text
message; tapping it on an iPhone opens Quick Look, which renders HTML with inline
CSS and nothing else. So the file may reference nothing outside itself, may carry
no script, and must escape every string that came from a model or a member.
"""

from datetime import UTC, datetime
from decimal import Decimal

from tests.summary.helpers import NOW, done_team, phase, snapshot, starter, team
from ultimate_guillotine.summary.artifact import (
    ARTIFACT_MAX_BYTES,
    artifact_filename,
    render_html,
    short_text,
)
from ultimate_guillotine.summary.color import EodColor
from ultimate_guillotine.summary.fixture import FIXTURE_NOW, fixture_eod
from ultimate_guillotine.summary.models import EodPacket
from ultimate_guillotine.summary.survival import simulate


def _packet(snap, *, odds: bool = True, reason: str | None = None) -> EodPacket:
    result = simulate(snap, simulations=200) if odds else None
    return EodPacket(snapshot=snap, result=result, coverage_pct=Decimal(100),
                     no_odds_reason=None if odds else (reason or "no schedule"))


def _fixture_packet() -> EodPacket:
    return EodPacket(snapshot=fixture_eod(), result=simulate(fixture_eod(), simulations=300),
                     coverage_pct=Decimal(100), no_odds_reason=None)


# -- the file -------------------------------------------------------------


def test_the_page_is_self_contained_and_static() -> None:
    html = render_html(_fixture_packet(), None, FIXTURE_NOW)
    lowered = html.lower()
    assert lowered.startswith("<!doctype html>")
    assert "<script" not in lowered
    assert "<img" not in lowered
    assert "<iframe" not in lowered
    assert "http://" not in lowered and "https://" not in lowered
    assert "<link" not in lowered
    assert 'name="viewport"' in lowered
    assert "<style>" in lowered
    assert len(html.encode()) < ARTIFACT_MAX_BYTES


def test_the_page_carries_every_section_and_every_live_team() -> None:
    packet = _fixture_packet()
    html = render_html(packet, None, FIXTURE_NOW)
    for live in packet.snapshot.live_teams():
        assert live.label in html
    for heading in ("The gulag", "On the block", "The board", "Roster watch", "Moves since"):
        assert heading in html
    assert "Week 6" in html
    assert "Member17" in html and "wk 5" in html
    assert "estimates, not rulings" in html


def test_model_and_member_text_is_escaped() -> None:
    color = EodColor(headline="<b>Knives</b> & forks", blurb="Member04 <script>alert(1)</script>")
    snap = snapshot((done_team(1, "100"), done_team(2, "90"), done_team(3, "80"),
                     done_team(4, "70", label="Tom & <Jerry>")))
    html = render_html(_packet(snap), color, NOW)
    assert "<b>Knives</b>" not in html
    assert "&lt;b&gt;Knives&lt;/b&gt; &amp; forks" in html
    assert "<script>" not in html
    assert "Tom &amp; &lt;Jerry&gt;" in html


def test_the_colour_leads_the_page_when_there_is_one() -> None:
    color = EodColor(headline="Two graves dug", blurb="Member04 is toast.")
    html = render_html(_packet(snapshot((done_team(1, "100"), done_team(2, "90"),
                                         done_team(3, "80"), done_team(4, "70")))), color, NOW)
    assert html.index("Two graves dug") < html.index("On the block")
    assert "Member04 is toast." in html


def test_factual_mode_shows_no_percentages_and_says_why() -> None:
    teams = (done_team(1, "100"), done_team(2, "52"), done_team(3, "50"),
             team(4, points="45", starters=(starter("remaining", projected=None),)))
    html = render_html(_packet(snapshot(teams), odds=False, reason="no schedule"), None, NOW)
    body = html.split("</style>", 1)[1]
    assert "%" not in body
    assert "No odds tonight: no schedule" in body


def test_the_outlook_page_shows_projections_not_zero_scores() -> None:
    snap = snapshot((team(1, starters=(starter("remaining", projected="100"),)),
                     team(2, starters=(starter("remaining", projected="90"),)),
                     team(3, starters=(starter("remaining", projected="80"),))),
                    day_state="outlook", games_final=0)
    html = render_html(_packet(snap), None, NOW)
    body = html.split("</style>", 1)[1]
    assert "Nothing has kicked off yet" in body
    assert "0.0" not in body


def test_the_gulag_pair_are_marked_on_the_board() -> None:
    teams = (done_team(1, "100"), done_team(2, "95"), done_team(3, "60"), done_team(4, "50"))
    snap = snapshot(teams, week=5, phase_=phase(5, "gulag", gulag=(3, 4), source="replay"))
    html = render_html(_packet(snap), None, NOW)
    assert "The gulag" in html
    assert "inferred from last week" in html
    assert html.count("⚔") >= 2


# -- the chat text that travels with the file -----------------------------


def test_the_short_text_is_the_header_the_colour_the_block_and_the_footer() -> None:
    packet = _fixture_packet()
    color = EodColor(headline="Knives out", blurb="Member18 is in trouble.")
    text = short_text(packet, color, FIXTURE_NOW)
    lines = text.splitlines()
    assert lines[0] == "🗡️ GUILLOTINE DAILY · Week 6 · Sunday"
    assert "🔥 Knives out" in text
    assert "⚔️ THE GULAG" in text
    assert "⚰️ ON THE BLOCK" in text
    assert "📊 THE BOARD" not in text
    assert "🩹" not in text
    assert "Full board attached" in text
    assert text.rstrip().endswith("estimates, not rulings")
    assert len(text) < 900


def test_the_short_text_without_colour_has_no_gap() -> None:
    text = short_text(_fixture_packet(), None, FIXTURE_NOW)
    assert "🔥" not in text
    assert "\n\n\n" not in text


def test_the_filename_names_the_week_and_the_local_date() -> None:
    assert artifact_filename(1, datetime(2026, 9, 14, 4, 50, tzinfo=UTC)) == (
        "guillotine-daily-week-1-2026-09-13.html"
    )
