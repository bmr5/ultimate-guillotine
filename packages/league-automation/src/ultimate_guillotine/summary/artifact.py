"""The HTML artifact: the whole summary as one self-contained file for Quick Look.

Ben (2026-09-10): send only the HTML file, named MonteCarlo-Date. The file contains
every section, the full board as a table, and the odds as bars.
Tapping it on an iPhone opens Quick Look, which renders
HTML with inline CSS and nothing else.

So the page references nothing outside itself: no script, no image, no stylesheet
link, no font, no URL. The styling is the board's own palette written inline.
Every string that came from a model or from a member's Sleeper profile goes
through :func:`html.escape`; the page is built from the same :class:`View` the
text renderer reads, so the two can never disagree about a rank or a number.
"""

from datetime import datetime
from decimal import Decimal
from html import escape

from ultimate_guillotine.summary.color import EodColor
from ultimate_guillotine.summary.models import LOCAL_TZ, EodPacket, TeamLine
from ultimate_guillotine.summary.render import (
    View,
    build_sections,
    move_suffix,
    moves_heading,
)

#: The League Agent spec's cap on a rendered artifact.
ARTIFACT_MAX_BYTES = 200 * 1024

#: Risk above which a board row's bar is red, and above which it is amber.
_RED = Decimal("0.50")
_AMBER = Decimal("0.20")

_CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#05070c;color:#f2f3f8;font:16px/1.45 -apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif;-webkit-text-size-adjust:100%}
main{max-width:640px;margin:0 auto;padding:20px 14px 36px}
.hero{padding:6px 2px 14px}
.kicker{font-size:13px;letter-spacing:.14em;text-transform:uppercase;color:#f0a24a;font-weight:700}
h1{margin:4px 0 6px;font-size:28px;line-height:1.15}
.sub{margin:0;color:#a3a9bd}
.card{background:rgba(11,14,23,.9);border:1px solid rgba(255,255,255,.1);border-radius:14px;padding:14px 14px 12px;margin:12px 0}
.card h2{margin:0 0 2px;font-size:17px}
.card .note{margin:0 0 10px;color:#a3a9bd;font-size:14px}
.fire{border-color:rgba(240,162,74,.45);background:rgba(240,162,74,.08)}
.fire h2{color:#f0a24a}
.fire p{margin:6px 0 0}
.row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 10px;padding:8px 0;border-top:1px solid rgba(255,255,255,.08)}
.row:first-of-type{border-top:0}
.row .who{font-weight:600}
.row .num{grid-column:1/-1;color:#a3a9bd;font-size:14px}
.pct{font-weight:700;white-space:nowrap}
.pct.red{color:#ff6b7a}.pct.amber{color:#f0a24a}.pct.safe{color:#a3a9bd}
.sweat{margin:10px 0 0;color:#a3a9bd;font-size:14px}
table{width:100%;border-collapse:collapse;font-size:14px}
.table-scroll{overflow-x:auto}
th{text-align:left;color:#a3a9bd;font-weight:600;font-size:12px;letter-spacing:.06em;text-transform:uppercase;padding:6px 4px;border-bottom:1px solid rgba(255,255,255,.12)}
td{padding:7px 4px;border-bottom:1px solid rgba(255,255,255,.06);vertical-align:middle}
td.n,th.n{text-align:right;white-space:nowrap}
td.rank{color:#a3a9bd;width:2em}
td.team{font-weight:600}
.bar{display:block;height:5px;border-radius:3px;background:rgba(255,255,255,.1);margin-top:4px;overflow:hidden}
.bar i{display:block;height:100%;background:#f0a24a}
.bar.red i{background:#ff6b7a}.bar.safe i{background:#5f6577}
.gulag td.team::before{content:"⚔ ";color:#ff6b7a}
.est{color:#a3a9bd}
.out{margin:10px 0 0;color:#a3a9bd;font-size:14px}
ul{margin:0;padding-left:18px}
li{margin:4px 0}
footer{margin-top:18px;color:#a3a9bd;font-size:13px;text-align:center}
@media(max-width:480px){table{font-size:12px}th{font-size:10px;letter-spacing:0}td,th{padding-left:3px;padding-right:3px}}
"""


def artifact_title(now: datetime) -> str:
    return f"MonteCarlo-{now.astimezone(LOCAL_TZ):%Y-%m-%d}"


def artifact_filename(now: datetime) -> str:
    return f"{artifact_title(now)}.html"


def _pct_class(view: View, team: TeamLine) -> str:
    probability = view.probability(team)
    if probability >= _RED:
        return "red"
    if probability >= _AMBER:
        return "amber"
    return "safe"


def _bar(view: View, team: TeamLine) -> str:
    width = int(view.probability(team) * 100)
    return f'<span class="bar {_pct_class(view, team)}"><i style="width:{width}%"></i></span>'


def _pair_row(view: View, team: TeamLine, *, to_lose: bool) -> str:
    """The team, its risk, and original, current and actual scoring figures."""
    risk = view.loss_risk(team) if to_lose else view.block_risk(team)
    cells = [f'<span class="who">{escape(team.label)}</span>']
    if risk is not None:
        cells.append(f'<span class="pct {_pct_class(view, team)}">{escape(risk)}</span>')
    cells.append(f'<span class="num">{escape(view.stand(team))}</span>')
    return f'<div class="row">{"".join(cells)}</div>'


def _hero(view: View, now: datetime) -> str:
    return (
        '<header class="hero"><div class="kicker">Monte Carlo</div>'
        f"<h1>{escape(artifact_title(now))}</h1>"
        f'<p class="sub">{escape(view.title(now))} · {escape(view.header_line())}</p></header>'
    )


def _colour_card(color: EodColor) -> str:
    return (
        '<section class="card fire">'
        f"<h2>🔥 {escape(color.headline)}</h2><p>{escape(color.blurb)}</p></section>"
    )


def _gulag_card(view: View) -> str | None:
    if not view.has_gulag_section():
        return None
    problem = view.gulag_problem()
    if problem is not None:
        return f'<section class="card"><h2>⚔️ The gulag</h2><p class="note">{escape(problem)}</p></section>'
    rows = "".join(_pair_row(view, team, to_lose=True) for team in view.gulag_pair())
    note = (
        '<p class="sweat">(pairing inferred from last week\'s scores)</p>'
        if view.gulag_provisional()
        else ""
    )
    return (
        '<section class="card"><h2>⚔️ The gulag</h2><p class="note">loser is out</p>'
        f"{rows}{note}</section>"
    )


def _block_card(view: View) -> str:
    top, _sweating = view.block()
    title = "The final" if view.block_title == "THE FINAL" else "On the block"
    rows = "".join(_pair_row(view, team, to_lose=False) for team in top)
    return (
        f'<section class="card"><h2>{view.block_emoji} {title}</h2>'
        f'<p class="note">{escape(view.block_note)}</p>{rows}</section>'
    )


def _sweating_card(view: View) -> str | None:
    _top, sweating = view.block()
    if not sweating:
        return None
    rows = "".join(_pair_row(view, team, to_lose=False) for team in sweating)
    return f'<section class="card"><h2>⚰️ Sweating</h2>{rows}</section>'


def _board_card(view: View) -> str:
    outlook, odds = view.outlook, view.result is not None
    heads = ['<th class="n">#</th>', "<th>Team</th>"]
    heads.extend(
        [
            '<th class="n">Original</th>',
            '<th class="n">Current</th>',
            '<th class="n">Actual</th>',
        ]
    )
    if not outlook:
        heads.append('<th class="n">Left</th>')
    if odds:
        heads.append('<th class="n">Risk</th>')
    rows: list[str] = []
    for rank, team in enumerate(view.ranked_board(), start=1):
        classes = ' class="gulag"' if view.in_gulag(team) else ""
        cells = [f'<td class="rank n">{rank}</td>', f'<td class="team">{escape(team.label)}</td>']
        cells.append(f'<td class="n">{escape(view.original_projected(team))}</td>')
        projected = escape(view.projected(team))
        if projected.startswith("~"):
            projected = f'<span class="est">{projected}</span>'
        cells.append(f'<td class="n">{projected}</td>')
        cells.append(f'<td class="n">{escape(view.actual(team))}</td>')
        if not outlook:
            cells.append(f'<td class="n">{view.pending_count(team)}</td>')
        if odds:
            cells.append(
                f'<td class="n"><span class="pct {_pct_class(view, team)}">'
                f"{escape(view.risk(team))}</span>{_bar(view, team)}</td>"
            )
        rows.append(f"<tr{classes}>{''.join(cells)}</tr>")
    out = view.out_line()
    out_html = f'<p class="out">{escape(out)}</p>' if out else ""
    ranking_note = (
        "Sorted by current projection; the block is ranked by risk."
        if odds
        else "Sorted by actual score while current projections and odds are unavailable."
    )
    return (
        '<section class="card"><h2>📊 The board</h2>'
        '<p class="note">Original: full-game projections for this lineup. '
        "Current: actual points plus projected scoring still to come. Actual: points scored. "
        f"{ranking_note}</p>"
        f'<div class="table-scroll"><table><thead><tr>{"".join(heads)}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
        f"{out_html}</section>"
    )


def _watch_card(view: View) -> str | None:
    notes = view.watch_notes()
    if not notes:
        return None
    items = "".join(f"<li><b>{escape(label)}:</b> {escape(note)}</li>" for label, note in notes)
    return f'<section class="card"><h2>🩹 Roster watch</h2><ul>{items}</ul></section>'


def _moves_card(view: View) -> str | None:
    moves = view.snap.moves
    if not moves:
        return None
    items = []
    for move in moves:
        legs = [f"+{name}" for name in move.adds] + [f"−{name}" for name in move.drops]
        items.append(
            f"<li><b>{escape(move.team_label)}:</b> "
            f"{escape(' '.join(legs))}{escape(move_suffix(move.kind, move.waiver_bid))}</li>"
        )
    heading = escape(moves_heading(view.snap, title_case=True))
    return f'<section class="card"><h2>🔁 {heading}</h2><ul>{"".join(items)}</ul></section>'


def render_html(packet: EodPacket, color: EodColor | None, now: datetime) -> str:
    """The whole summary as one page. Self-contained, static, escaped."""
    view = View(packet)
    cards = [_hero(view, now)]
    if color is not None:
        cards.append(_colour_card(color))
    cards.extend(
        c
        for c in (
            _gulag_card(view),
            _block_card(view),
            _sweating_card(view),
            _board_card(view),
            _watch_card(view),
            _moves_card(view),
        )
        if c
    )
    cards.append(f"<footer>{escape(' · '.join(view.footer_parts()))}</footer>")
    title = escape(artifact_title(now))
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{title}</title><style>{_CSS}</style></head>"
        f"<body><main>{''.join(cards)}</main></body></html>\n"
    )


def short_text(packet: EodPacket, color: EodColor | None, now: datetime) -> str:
    """Internal recap text for storage and draft previews, never sent to chat.

    The colour leads the HTML file only, so ``color`` is deliberately unused here.
    """
    del color
    sections = build_sections(packet, now)
    parts = [sections.header]
    if sections.gulag:
        parts.append(sections.gulag)
    parts.append(sections.block)
    if sections.sweating:
        parts.append(sections.sweating)
    parts.append(sections.footer)
    return "\n\n".join(parts)
