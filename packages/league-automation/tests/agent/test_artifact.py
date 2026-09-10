"""The write-up is the agent's; the file is the package's. Everything dangerous is dropped."""

from datetime import UTC, datetime

from ultimate_guillotine.agent.answer import Report, Source
from ultimate_guillotine.agent.artifact import (
    ARTIFACT_MAX_BYTES,
    artifact_filename,
    external_references,
    render_artifact,
    sanitize_body,
    text_content,
)

SOURCE = "https://example.com/bowers"
GENERATED = datetime(2026, 10, 8, 20, 0, tzinfo=UTC)
CITED = (Source(url=SOURCE, claim="Bowers is out 1-2 weeks"),)


def _report(body: str, sources=CITED) -> Report:
    return Report(title="Holding Bowers", question="Who could hold Bowers?",
                  html_body=body, sources=list(sources))


def test_scripts_styles_and_frames_are_removed_with_their_content() -> None:
    body = "<p>ok</p><script>alert(1)</script><style>p{}</style><iframe src='https://x'></iframe>"
    cleaned = sanitize_body(body, {SOURCE})
    assert cleaned == "<p>ok</p>"


def test_images_forms_and_event_handlers_are_dropped() -> None:
    body = '<p onclick="x()">hi</p><img src="https://x/y.png"><form><input></form>'
    cleaned = sanitize_body(body, {SOURCE})
    assert "onclick" not in cleaned and "<img" not in cleaned and "<form" not in cleaned
    assert "<p>hi</p>" in cleaned


def test_links_survive_only_to_cited_sources_or_anchors() -> None:
    body = (f'<a href="{SOURCE}">cited</a> <a href="https://evil.example/x">not</a> '
            '<a href="#options">jump</a> <a href="javascript:alert(1)">js</a>')
    cleaned = sanitize_body(body, {SOURCE})
    assert f'href="{SOURCE}"' in cleaned and 'rel="noopener noreferrer"' in cleaned
    assert "evil.example" not in cleaned and "not" in cleaned
    assert 'href="#options"' in cleaned
    assert "javascript:" not in cleaned


def test_classes_are_filtered_to_the_allowlist() -> None:
    cleaned = sanitize_body('<p class="card evil pro">x</p><span class="evil">y</span>', set())
    assert '<p class="card pro">x</p>' in cleaned
    assert "<span>y</span>" in cleaned


def test_the_rendered_file_is_self_contained() -> None:
    html = render_artifact(
        _report("<h2>Options</h2><p class='card'>Member02 holds him for 40 FAAB.</p>"),
        asker_label="Member05", season=2026, week=6, source_line="Source: rosters as of 3:00pm",
        generated_at=GENERATED,
    )
    assert "<title>Holding Bowers</title>" in html
    assert "Member05" in html and "Week 6" in html and "Who could hold Bowers?" in html
    assert "Member02 holds him for 40 FAAB." in html
    assert f'<a href="{SOURCE}"' in html and "Bowers is out 1-2 weeks" in html
    assert external_references(html) == []
    assert "<script" not in html and "<img" not in html


def test_external_references_finds_anything_the_file_would_load() -> None:
    assert external_references('<link rel="stylesheet" href="https://cdn/x.css">') == [
        "https://cdn/x.css"
    ]
    assert external_references("<style>@import url(https://cdn/y.css);</style>") == [
        "https://cdn/y.css"
    ]
    assert external_references('<img src="https://cdn/z.png">') == ["https://cdn/z.png"]


def test_the_title_makes_the_file_name() -> None:
    assert artifact_filename("Holding Brock Bowers: the options", 6) == (
        "holding-brock-bowers-the-options-week-6.html"
    )
    assert artifact_filename("!!!", 12) == "answer-week-12.html"


def test_text_content_strips_markup() -> None:
    assert text_content("<h2>Options</h2><p class='card'>A <b>B</b></p>") == "Options A B"


def test_the_size_cap_is_the_spec_figure() -> None:
    assert ARTIFACT_MAX_BYTES == 200_000
