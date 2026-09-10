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
#: Dropped tags that carry no end tag, so counting one would swallow the rest of the file.
VOID_DROPPED = frozenset({"embed"})
_TEMPLATE_PATH = Path(__file__).resolve().parents[5] / "agents" / "league-agent" / "artifact.html"
#: Every way a byte of HTML or CSS asks a browser to fetch something.
_EXTERNAL = re.compile(
    r"""(?:
          \b(?:src|srcset|poster|data)\s*=\s*["']?   # img/script/video/object attributes
        | <(?:link|base)[^>]+href\s*=\s*["']?        # a stylesheet, or a new base for every URL
        | url\(\s*["']?                              # CSS url(...)
        | @import\s*["']                             # CSS @import "..."
    )(https?://[^"')\s>]+)""",
    re.IGNORECASE | re.VERBOSE,
)
#: A template slot. Anything else shaped like one is left where it stands.
_TOKEN = re.compile(r"__[A-Z_]+__")


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
    """The prose in some markup, with a dropped element's content left out.

    Skipping must never outlive its element, because a scan that stops early
    is a scan that misses what comes after it. So a tag that carries no end
    tag is not counted at all, and text a dropped tag swallowed without ever
    closing is handed back at the end -- a stray line of CSS in the scan costs
    nothing; a missed phone number costs everything.
    """

    #: ``<style>`` must not put the parser into CDATA mode: unclosed, it would eat the rest.
    CDATA_CONTENT_ELEMENTS: tuple[str, ...] = ()

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0
        self._swallowed: list[str] = []

    def handle_startendtag(self, tag: str, attrs) -> None:
        """``<embed/>`` has no content to skip and no end tag to balance: ignore it."""

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in DROPPED_WITH_CONTENT and tag not in VOID_DROPPED:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in DROPPED_WITH_CONTENT and self._skip:
            self._skip -= 1
            if not self._skip:
                self._swallowed.clear()

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            (self._swallowed if self._skip else self.parts).append(text)

    def text(self) -> str:
        # Anything still swallowed belongs to a dropped tag that never closed.
        return " ".join(self.parts + self._swallowed)


def text_content(markup: str) -> str:
    """The words in some HTML, for the verifier's scans."""
    collector = _TextCollector()
    collector.feed(markup)
    collector.close()
    return collector.text()


def external_references(markup: str) -> list[str]:
    """Every URL the file would load on open: none, for a finished artifact."""
    return _EXTERNAL.findall(markup)


def artifact_filename(title: str, week: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60].strip("-")
    return f"{slug or 'answer'}-week-{week}.html"


def _sources_html(sources: Sequence[Source]) -> str:
    kept = [s for s in sources if s.url.startswith("https://")]
    if not kept:
        # Including when every source was dropped: an empty <ol> says nothing.
        return '<p class="muted">No outside sources; league data only.</p>'
    items = "".join(
        f'<li><a href="{html.escape(s.url, quote=True)}" rel="{LINK_REL}">'
        f"{html.escape(s.claim)}</a></li>"
        for s in kept
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
    # One pass, so no substituted value can be read as a later token: a report
    # titled __BODY__ is a title, not an instruction.
    return _TOKEN.sub(lambda m: replacements.get(m.group(0), m.group(0)), _template())
