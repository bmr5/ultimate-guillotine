"""The message: every section, in the words the league reads on a phone.

Plain text, no markdown -- iMessage renders asterisks as asterisks -- and short
lines, because eighteen teams have to fit under a thumb. The delivery layer
appends the signature; nothing here does.

**Only what the league already says out loud.** Every name is a team's public
label or a player's Sleeper name, every number is a score, a projection or an
estimate this run computed, and the join key never reaches this module at all.
The colour, when there is one, has already been through the verifier.

**A figure that is unknown says so.** Factual mode -- no schedule, coverage below
the gate -- renders no percentage anywhere and names the reason in the footer; a
projected finish built on an estimated starter carries a ``~``; a missing score
row is counted in the footer rather than shown as a zero that reads as a score.

:class:`View` is the one reading of a packet -- who is live, who is in the gulag,
who is on the block, the board's order, the roster notes -- and both this text
renderer and the HTML artifact (:mod:`~ultimate_guillotine.summary.artifact`)
are written over it, so the two can never rank a team differently.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from ultimate_guillotine.summary.color import EodColor
from ultimate_guillotine.summary.lineup import UNAVAILABLE_STATUSES
from ultimate_guillotine.summary.models import LOCAL_TZ, EodPacket, TeamLine, TeamOdds

#: Below this a team is not worth a "sweating" mention.
SWEATING_FLOOR = Decimal("0.10")
ROSTER_WATCH_LINES = 8
MOVES_LINES = 6

_ONE = Decimal(1)
_ZERO = Decimal(0)


def percent(probability: Decimal, *, settled: bool) -> str:
    """A whole percentage, the tails named, and words when nothing is left to play."""
    if settled:
        if probability >= _ONE:
            return "locked"
        if probability <= _ZERO:
            return "safe"
    if probability <= _ZERO:
        return "0%"
    if probability >= _ONE:
        return "100%"
    hundred = probability * 100
    if hundred < 1:
        return "<1%"
    if hundred > 99:
        return ">99%"
    return f"{int(hundred.quantize(Decimal(1), rounding=ROUND_HALF_UP))}%"


def plural(count: int, singular: str, plural_form: str) -> str:
    return singular if count == 1 else plural_form


def clock(stamp: datetime) -> str:
    return stamp.astimezone(LOCAL_TZ).strftime("%-I:%M %p") + " CT"


def window_stamp(stamp: datetime) -> str:
    """``Fri 11:50 PM``: the weekday and the clock, in the league's time.

    Never title-cased downstream: ``.title()`` turns ``PM`` into ``Pm``.
    """
    local = stamp.astimezone(LOCAL_TZ)
    return f"{local:%a} {local.strftime('%-I:%M %p')}"


def moves_heading(snap, *, title_case: bool = False) -> str:
    """``MOVES SINCE FRI 11:50 PM``, or ``RECENT MOVES`` when no window was recorded."""
    if snap.moves_since is None:
        return "Recent moves" if title_case else "RECENT MOVES"
    stamp = window_stamp(snap.moves_since)
    return f"Moves since {stamp}" if title_case else f"MOVES SINCE {stamp.upper()}"


def move_suffix(kind: str, bid: int | None) -> str:
    if kind == "waiver":
        return f" (waiver ${bid})" if bid is not None else " (waiver)"
    if kind == "trade":
        return " (trade)"
    if kind == "commissioner":
        return " (commish)"
    return ""


class View:
    """One packet, read once: who is live, who is paired, who is ranked where."""

    def __init__(self, packet: EodPacket) -> None:
        self.packet = packet
        self.snap = packet.snapshot
        self.result = packet.result
        self.outlook = self.snap.day_state == "outlook"
        self.live = self.snap.live_teams()
        self.settled = not any(t.pending() for t in self.live)
        pair = tuple(
            t.team_id for t in self.live if t.team_id in self.snap.phase.gulag_team_ids
        )
        self.gulag = pair if len(pair) == 2 and self.snap.phase.kind in ("gulag", "double") else ()
        self.pool = [t for t in self.live if t.team_id not in self.gulag]
        kind = self.snap.phase.kind
        if kind in ("entry", "gulag"):
            self.block_emoji, self.block_title = "⚰️", "ON THE BLOCK"
            self.block_note = f"bottom 2 enter the Week {self.snap.week + 1} gulag"
            self.block_count = 2
        elif kind == "final":
            self.block_emoji, self.block_title = "🏆", "THE FINAL"
            self.block_note, self.block_count = "lower score is runner-up", 1
        else:
            self.block_emoji, self.block_title = "⚰️", "ON THE BLOCK"
            self.block_note, self.block_count = "lowest score is cut", 1

    # -- one team ----------------------------------------------------------

    def odds(self, team: TeamLine) -> TeamOdds | None:
        return None if self.result is None else self.result.teams.get(team.team_id)

    def probability(self, team: TeamLine) -> Decimal:
        odds = self.odds(team)
        return _ZERO if odds is None else odds.probability

    def projected(self, team: TeamLine) -> str:
        odds = self.odds(team)
        if odds is None:
            return "—"
        mark = "~" if odds.is_estimated else ""
        return f"{mark}{odds.projected_final.quantize(Decimal(1), rounding=ROUND_HALF_UP)}"

    def risk(self, team: TeamLine) -> str:
        return percent(self.probability(team), settled=self.settled)

    def pending_count(self, team: TeamLine) -> int:
        return len(team.pending())

    def left(self, team: TeamLine) -> str:
        return f"{self.pending_count(team)} left"

    def in_gulag(self, team: TeamLine) -> bool:
        return team.team_id in self.gulag

    def by_risk(self, teams: Sequence[TeamLine]) -> list[TeamLine]:
        if self.result is None:
            return sorted(teams, key=lambda t: (t.points, t.label))
        return sorted(teams, key=lambda t: (-self.probability(t), t.points, t.label))

    # -- the sections' data -------------------------------------------------

    def header_line(self) -> str:
        snap = self.snap
        if snap.day_state == "outlook":
            return "Nothing has kicked off yet · the projected board"
        if snap.day_state == "final":
            return "Every game is in the books · standings pending the commish"
        if snap.day_state == "unknown":
            return "Game status unavailable tonight"
        left = sum(1 for t in self.live if t.pending())
        return (
            f"{snap.games_final} of {snap.games_total} games final · "
            f"{left} {plural(left, 'team', 'teams')} still "
            f"{plural(left, 'has', 'have')} players to go"
        )

    def title(self, now: datetime) -> str:
        return f"Week {self.snap.week} · {now.astimezone(LOCAL_TZ):%A}"

    def has_gulag_section(self) -> bool:
        return self.snap.phase.kind in ("gulag", "double")

    def gulag_problem(self) -> str | None:
        """Why there is no pair to show, or ``None`` when there is one."""
        if self.snap.phase.gulag_source == "unknown":
            return "pairing unknown (a past week has no scores on file)"
        if not self.gulag:
            return "pairing unresolved (a named team is already out)"
        return None

    def gulag_provisional(self) -> bool:
        return self.snap.phase.gulag_source == "replay"

    def gulag_pair(self) -> list[TeamLine]:
        return self.by_risk([t for t in self.live if t.team_id in self.gulag])

    def block(self) -> tuple[list[TeamLine], list[TeamLine]]:
        """The teams in the adverse position, and the ones sweating behind them."""
        ranked = self.by_risk(self.pool)
        top = ranked[: self.block_count]
        if self.result is None:
            return top, []
        sweating = [
            t for t in ranked[self.block_count:] if self.probability(t) >= SWEATING_FLOOR
        ]
        return top, sweating

    def ranked_board(self) -> list[TeamLine]:
        if self.result is not None:
            return sorted(
                self.live,
                key=lambda t: (
                    -(self.odds(t).projected_final if self.odds(t) else _ZERO),
                    -t.points,
                    t.label,
                ),
            )
        return sorted(self.live, key=lambda t: (-t.points, t.label))

    def eliminated(self) -> list[TeamLine]:
        return sorted(
            (t for t in self.snap.teams if t.is_eliminated),
            key=lambda t: (t.eliminated_week or 0, t.label),
        )

    def out_line(self) -> str | None:
        out = self.eliminated()
        if not out:
            return None
        return "Out: " + ", ".join(
            f"{t.label} (wk {t.eliminated_week})" if t.eliminated_week else t.label for t in out
        )

    def watch_notes(self) -> list[tuple[str, str]]:
        """``(label, note)`` for every roster problem, uncapped, in board order."""
        notes: list[tuple[str, str]] = []
        for team in self.live:
            empties = team.empty_slots()
            if empties:
                notes.append((team.label, f"{empties} empty {plural(empties, 'slot', 'slots')}"))
            for starter in team.out_starters():
                if starter.injury_status in UNAVAILABLE_STATUSES:
                    notes.append(
                        (team.label, f"{starter.name} ({starter.injury_status}) still in the lineup")
                    )
                else:
                    notes.append(
                        (team.label, f"{starter.name} ({starter.injury_status}, no projection)")
                    )
            for starter in team.unprojected_pending():
                notes.append((team.label, f"{starter.name} has no projection"))
        return notes

    def footer_parts(self) -> list[str]:
        snap = self.snap
        parts: list[str] = []
        if self.result is not None:
            parts.append(f"{self.result.simulations:,} sims on Sleeper projections")
        else:
            parts.append(f"No odds tonight: {self.packet.no_odds_reason}")
        parts.append(
            f"scores as of {clock(snap.scores_synced_at)}"
            if snap.scores_synced_at is not None
            else "no scores on file"
        )
        missing = sum(1 for t in self.live if not t.has_score_row)
        if missing:
            parts.append(
                f"{missing} {plural(missing, 'team', 'teams')} "
                f"{plural(missing, 'has', 'have')} no score on file"
            )
        parts.append("estimates, not rulings")
        return parts

    # -- one line of text ----------------------------------------------------

    def stand(self, team: TeamLine) -> str:
        """Where a team stands: its projected finish and its actual score.

        Ben's line (2026-09-10): the team, its risk, ``Projected · Actual``. Before
        kickoff nobody has scored, so the actual is left off; in factual mode
        there is no projected finish, so the actual and the players left stand.
        """
        if self.result is None:
            return self.left(team) if self.outlook else f"actual {team.points:.1f} · {self.left(team)}"
        if self.outlook:
            return f"proj {self.projected(team)}"
        return f"proj {self.projected(team)} · actual {team.points:.1f}"

    def team_line(self, team: TeamLine, *, risk: str | None = None) -> str:
        """``Ben R · 37% · proj 88 · actual 7.8``, the risk left out when there is none."""
        parts = [team.label]
        if risk is not None:
            parts.append(risk)
        parts.append(self.stand(team))
        return " · ".join(parts)

    def loss_risk(self, team: TeamLine) -> str | None:
        """The gulag's wording: ``84% to lose``, or ``safe`` on its own."""
        if self.result is None:
            return None
        risk = self.risk(team)
        return risk if risk == "safe" else f"{risk} to lose"

    def block_risk(self, team: TeamLine) -> str | None:
        return None if self.result is None else self.risk(team)


@dataclass(frozen=True)
class Sections:
    """The message in pieces, so the chat text and the short text share them."""

    header: str
    gulag: str | None
    block: str
    sweating: str | None
    board: str
    watch: str | None
    moves: str | None
    footer: str

    def middle(self) -> list[str]:
        return [
            s
            for s in (self.gulag, self.block, self.sweating, self.board, self.watch, self.moves)
            if s
        ]


def _header(view: View, now: datetime) -> str:
    return f"🗡️ GUILLOTINE DAILY · {view.title(now)}\n{view.header_line()}"


def _gulag_section(view: View) -> str | None:
    if not view.has_gulag_section():
        return None
    problem = view.gulag_problem()
    if problem is not None:
        return f"⚔️ THE GULAG · {problem}"
    lines = ["⚔️ THE GULAG · loser is out"]
    for team in view.gulag_pair():
        lines.append(view.team_line(team, risk=view.loss_risk(team)))
    if view.gulag_provisional():
        lines.append("(pairing inferred from last week's scores)")
    return "\n".join(lines)


def _block_section(view: View) -> str:
    top, _sweating = view.block()
    lines = [f"{view.block_emoji} {view.block_title} · {view.block_note}"]
    for team in top:
        lines.append(view.team_line(team, risk=view.block_risk(team)))
    return "\n".join(lines)


def _sweating_section(view: View) -> str | None:
    """The teams behind the block at ten percent or more, one line each."""
    _top, sweating = view.block()
    if not sweating:
        return None
    lines = ["⚰️ SWEATING"]
    for team in sweating:
        lines.append(view.team_line(team, risk=view.block_risk(team)))
    return "\n".join(lines)


def _board_section(view: View) -> str:
    outlook = view.outlook
    if view.result is not None:
        header = "📊 THE BOARD · proj · risk" if outlook else "📊 THE BOARD · score · proj · left · risk"
    else:
        header = "📊 THE BOARD · proj" if outlook else "📊 THE BOARD · score · left"
    lines = [header]
    for rank, team in enumerate(view.ranked_board(), start=1):
        parts = [f"{rank}. {team.label}"]
        if not outlook:
            parts.append(f"{team.points:.1f}")
        if view.result is not None:
            parts.append(view.projected(team))
        if not outlook:
            parts.append(str(view.pending_count(team)))
        if view.result is not None:
            risk = view.risk(team)
            parts.append(f"⚔{risk}" if view.in_gulag(team) else risk)
        lines.append(" · ".join(parts))
    out = view.out_line()
    if out:
        lines.append(out)
    return "\n".join(lines)


def _watch_section(view: View) -> str | None:
    notes = [f"{label}: {note}" for label, note in view.watch_notes()]
    if not notes:
        return None
    if len(notes) > ROSTER_WATCH_LINES:
        notes = [*notes[:ROSTER_WATCH_LINES], f"+{len(notes) - ROSTER_WATCH_LINES} more"]
    return "\n".join(["🩹 ROSTER WATCH", *notes])


def _moves_section(view: View) -> str | None:
    moves = view.snap.moves
    if not moves:
        return None
    lines = [f"🔁 {moves_heading(view.snap)}"]
    for move in moves[:MOVES_LINES]:
        legs = [f"+{name}" for name in move.adds] + [f"−{name}" for name in move.drops]
        lines.append(f"{move.team_label}: {' '.join(legs)}{move_suffix(move.kind, move.waiver_bid)}")
    if len(moves) > MOVES_LINES:
        lines.append(f"+{len(moves) - MOVES_LINES} more")
    return "\n".join(lines)


def build_sections(packet: EodPacket, now: datetime) -> Sections:
    view = View(packet)
    return Sections(
        header=_header(view, now),
        gulag=_gulag_section(view),
        block=_block_section(view),
        sweating=_sweating_section(view),
        board=_board_section(view),
        watch=_watch_section(view),
        moves=_moves_section(view),
        footer=" · ".join(view.footer_parts()),
    )


def facts_text(packet: EodPacket) -> str:
    """The sections the colour is written over and checked against: no header,
    no footer, no colour."""
    view = View(packet)
    sections = (
        _gulag_section(view),
        _block_section(view),
        _sweating_section(view),
        _board_section(view),
        _watch_section(view),
        _moves_section(view),
    )
    return "\n\n".join(s for s in sections if s)


def colour_text(color: EodColor) -> str:
    return f"🔥 {color.headline}\n{color.blurb}"


def render(packet: EodPacket, color: EodColor | None, now: datetime) -> str:
    """The whole message, unsigned."""
    sections = build_sections(packet, now)
    parts = [sections.header]
    if color is not None:
        parts.append(colour_text(color))
    parts.extend(sections.middle())
    parts.append(sections.footer)
    return "\n\n".join(parts)
