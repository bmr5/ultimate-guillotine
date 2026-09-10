"""The HTML artifact: the agent writes the body, the package makes it a safe file.

An allowlist, never a blocklist. ``nh3`` keeps the listed tags, the two listed
attributes and the six listed classes and drops everything else; links survive
only to a cited source or to an anchor in the document; the template supplies
every byte of CSS inline; and :func:`external_references` is the test that the
finished file would load nothing from anywhere.
"""

import html
import re
from collections.abc import Collection, Sequence
from datetime import datetime
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

import nh3

from ultimate_guillotine.agent.answer import Report, Source

ARTIFACT_MAX_BYTES = 200_000
ALLOWED_TAGS = frozenset({
    "h1", "h2", "h3", "h4", "p", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th",
    "td", "strong", "em", "b", "i", "br", "hr", "blockquote", "details", "summary", "a",
    "span", "div", "code", "pre",
})
ALLOWED_CLASSES = frozenset({"card", "pro", "con", "num", "tag", "muted"})
#: What ``nh3`` puts on every surviving link -- and hands back to the attribute filter.
LINK_REL = "noopener noreferrer"
#: Removed with their content: a script's body is not prose.
DROPPED_WITH_CONTENT = frozenset({
    "script", "style", "iframe", "object", "embed", "svg", "form", "noscript", "template",
    "math",
})
_TEMPLATE_PATH = Path(__file__).resolve().parents[5] / "agents" / "league-agent" / "artifact.html"
_EXTERNAL = re.compile(
    r"""(?:\bsrc\s*=\s*["']?|<link[^>]+href\s*=\s*["']?|url\(\s*["']?)(https?://[^"')\s>]+)""",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def _template() -> str:
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def sanitize_body(html_body: str, allowed_urls: Collection[str]) -> str:
    """The body with only the allowlisted markup left in it."""
    allowed = {url for url in allowed_urls if url.startswith("https://")}

    def attribute_filter(tag: str, attr: str, value: str) -> str | None:
        if attr == "href":
            if value.startswith("#"):
                return value
            return value if value in allowed else None
        if attr == "class":
            kept = [c for c in value.split() if c in ALLOWED_CLASSES]
            return " ".join(kept) or None
        if tag == "a" and attr == "rel" and value == LINK_REL:
            # nh3 adds this one itself, then offers it to the filter like any other.
            return value
        return None

    return nh3.clean(
        html_body,
        tags=set(ALLOWED_TAGS),
        clean_content_tags=set(DROPPED_WITH_CONTENT),
        attributes={"*": {"class"}, "a": {"href", "class"}},
        attribute_filter=attribute_filter,
        url_schemes={"https"},
        link_rel=LINK_REL,
        strip_comments=True,
    )


class _TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in DROPPED_WITH_CONTENT:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in DROPPED_WITH_CONTENT and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def text_content(markup: str) -> str:
    """The words in some HTML, for the verifier's scans."""
    collector = _TextCollector()
    collector.feed(markup)
    return " ".join(collector.parts)


def external_references(markup: str) -> list[str]:
    """Every URL the file would load on open: none, for a finished artifact."""
    return _EXTERNAL.findall(markup)


def artifact_filename(title: str, week: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60].strip("-")
    return f"{slug or 'answer'}-week-{week}.html"


def _sources_html(sources: Sequence[Source]) -> str:
    if not sources:
        return '<p class="muted">No outside sources; league data only.</p>'
    items = "".join(
        f'<li><a href="{html.escape(s.url, quote=True)}" rel="{LINK_REL}">'
        f"{html.escape(s.claim)}</a></li>"
        for s in sources
        if s.url.startswith("https://")
    )
    return f"<ol>{items}</ol>"


def render_artifact(
    report: Report,
    *,
    asker_label: str | None,
    season: int,
    week: int,
    source_line: str,
    generated_at: datetime,
) -> str:
    """The finished file: sanitized body inside the versioned template."""
    body = sanitize_body(report.html_body, {s.url for s in report.sources})
    asker = f"Asked by {html.escape(asker_label)}" if asker_label else "Asked in the league chat"
    meta = f"{asker} · {season} season · Week {week}"
    replacements = {
        "__TITLE__": html.escape(report.title),
        "__META__": meta,
        "__QUESTION__": html.escape(report.question or ""),
        "__BODY__": body,
        "__SOURCE_LINE__": html.escape(source_line),
        "__SOURCES__": _sources_html(report.sources),
        "__GENERATED__": html.escape(generated_at.strftime("%Y-%m-%d %H:%M UTC")),
    }
    rendered = _template()
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    return rendered
